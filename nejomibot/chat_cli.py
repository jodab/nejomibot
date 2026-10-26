"""nejomibot-chat: the bot from a terminal, as its first admin has it in a
direct chat with the bot. In the bot's container:

  podman exec -it nejomibot nejomibot-chat                 a chat
  podman exec nejomibot nejomibot-chat /weather Helsinki   one message
  echo "/msg 1 Dinner at six" | podman exec -i nejomibot nejomibot-chat
  podman exec -i nejomibot nejomibot-chat -a - /avatar < logo.png
  tar -c *.jpg | podman exec -i nejomibot nejomibot-chat -a - --to 1,2 Our trip
  podman exec nejomibot nejomibot-chat --recent 20         messages received
  podman exec nejomibot nejomibot-chat --follow            and as they come

The running bot takes each message as from its first admin in a direct chat
with it, through the same handlers as a message from Signal, and answers
here instead (terminal.py): what posts to other chats, as /msg and /run do,
posts there. Without a message, standard input is the message, or in a
terminal, the chat goes on a line a message, and a line that ends in \\ goes
on in the next. -a attaches a file, or with -, standard input: a file, or
the files in a tar archive, 25 MB together at most. --to CHATS posts the
message to chats from /chats, as /msg does, and needs no text for files.

--recent and --follow show the messages the bot has received, in every
chat. --json prints what the bot says as JSON, an object a line, for
scripts, and --save DIR saves the files in it to DIR.

It talks to the bot over a Unix socket in Linux's abstract namespace, as
nejomibot-healthcheck does, which the bot answers only for its own user and
root. It imports nothing else of the bot's, so it starts quickly.
"""

import argparse
import base64
import contextlib
import io
import json
import mimetypes
import os
import re
import socket
import sys
import tempfile
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# The bot listens on it, in the network namespace it shares with
# signal-cli-rest-api
SOCKET = "\0nejomibot-chat"
# What a message's files come to, together, and the most of a received file
# --save fetches: they pass through the bot's memory
MAX_ATTACHED = 25_000_000  # bytes
# The messages the bot keeps for --recent: the latest it received
RECENT = 100
CONNECT_TIMEOUT = 5  # seconds
# Seconds to wait for the answers: /msg with a video to several chats takes
# a while, and a bot that takes longer is stuck
ANSWER_TIMEOUT = 600
CHATS = re.compile(r"^\d+(?:,\d+)*$")
UNKNOWN = "application/octet-stream"
# How files start, for those without a name to say what they are, as on
# standard input and in the bot's answers: the first that fits
SIGNATURES = (
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"GIF8", "image/gif"),
    (8, b"WEBP", "image/webp"),
    (4, b"ftypheic", "image/heic"),
    (4, b"ftypmif1", "image/heif"),
    (4, b"ftypavif", "image/avif"),
    (4, b"ftypqt", "video/quicktime"),
    (4, b"ftyp", "video/mp4"),
    (0, b"%PDF-", "application/pdf"),
)
# Where a tar archive says it is one
TAR_MAGIC = slice(257, 262), b"ustar"
# The terminal's styles for Signal's; it shows everything in monospace
ANSI = {"BOLD": "1", "ITALIC": "3", "STRIKETHROUGH": "9", "SPOILER": "7"}

EXAMPLES = """\
examples, from the host:
  podman exec -it nejomibot nejomibot-chat               a chat
  podman exec nejomibot nejomibot-chat /weather Helsinki
  echo "/msg 1 Dinner at six" | podman exec -i nejomibot nejomibot-chat
  podman exec -i nejomibot nejomibot-chat -a - /avatar < logo.png
  tar -c *.jpg | podman exec -i nejomibot nejomibot-chat -a - --to 1,2 Our trip
  podman exec nejomibot nejomibot-chat --recent 20
  podman exec nejomibot nejomibot-chat --follow
  podman exec nejomibot nejomibot-chat --save /data/saved /photo
"""


class Refused(Exception):
    """What the bot can't do, or nejomibot-chat can't ask it, in words for
    the terminal."""


def content_type(data: bytes, name: str = "") -> str:
    """What kind of file it is: by its name, else by how it starts."""
    if name and (guessed := mimetypes.guess_type(name)[0]):
        return guessed
    for at, start, kind in SIGNATURES:
        if data[at : at + len(start)] == start:
            return kind
    return UNKNOWN


def size_text(size: int) -> str:
    """E.g. 1.2 MB, 340 kB, 677 bytes."""
    if size >= 1_000_000:
        return f"{size / 1_000_000:.3g} MB"
    if size >= 1000:
        return f"{size / 1000:.3g} kB"
    return f"{size} bytes"


@dataclass(frozen=True)
class File:
    name: str  # without its folder; none for standard input's
    data: bytes

    @property
    def header(self) -> dict[str, Any]:
        """The file, as the request names it: its bytes follow it."""
        return {
            "filename": self.name,
            "content_type": content_type(self.data, self.name),
            "size": len(self.data),
        }


def read_file(path: str) -> list[File]:
    """The file at path, or with -, standard input: a file, or the files in a
    tar archive. Raises Refused."""
    if path != "-":
        try:
            if (size := Path(path).stat().st_size) > MAX_ATTACHED:
                raise Refused(f"{path} is {size_text(size)}, over 25 MB")
            return [File(Path(path).name, Path(path).read_bytes())]
        except OSError as e:
            raise Refused(f"Can't read {path}: {e.strerror or e}") from e
    # A little more, for a tar archive's own headers
    data = sys.stdin.buffer.read(MAX_ATTACHED + 1_000_000)
    where, magic = TAR_MAGIC
    if data[where] != magic:
        return [File("", data)]
    # Here alone: the bot imports this module too, and needs no tarfile
    import tarfile

    files: list[File] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive:
                if member.isfile() and (found := archive.extractfile(member)):
                    files.append(File(Path(member.name).name, found.read()))
    except tarfile.TarError as e:
        raise Refused(f"Can't read the tar archive: {e}") from e
    return files


def read_files(paths: Sequence[str]) -> list[File]:
    """The files to attach. Raises Refused."""
    files = [file for path in paths for file in read_file(path)]
    if (size := sum(len(file.data) for file in files)) > MAX_ATTACHED:
        raise Refused(f"The files are {size_text(size)} together, over 25 MB")
    return files


def exchange(
    request: dict[str, Any],
    files: Sequence[File] = (),
    timeout: float | None = ANSWER_TIMEOUT,
) -> Generator[dict[str, Any]]:
    """Ask the bot, sending the files after the request, and yield what it
    says, an object each. Raises Refused. Once it has sent them, it says it
    has, by closing its side of the connection; but to follow messages, it
    keeps it open, so the bot sees when it goes."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(CONNECT_TIMEOUT)
            connection.connect(SOCKET)
            connection.settimeout(timeout)
            connection.sendall(json.dumps(request).encode() + b"\n")
            for file in files:
                connection.sendall(file.data)
            if not request.get("follow"):
                connection.shutdown(socket.SHUT_WR)
            with connection.makefile("rb") as said:
                for line in said:
                    found = json.loads(line)
                    if "error" in found:
                        raise Refused(found["error"])
                    yield found
    except TimeoutError as e:
        raise Refused("The bot didn't answer in time.") from e
    except OSError as e:
        raise Refused(
            f"The bot doesn't answer ({e.strerror or e}): it isn't running, or "
            "it's still starting."
        ) from e


def shows_styles() -> bool:
    """Whether standard output is a terminal that shows text styles."""
    return (
        sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
        and os.environ.get("TERM") != "dumb"
    )


@dataclass(frozen=True)
class Output:
    """How what the bot says is shown: as JSON, or as text, styled for a
    terminal; with the files saved to a folder, or not."""

    json: bool = False
    save: Path | None = None
    styled: bool = False

    def show(self, said: dict[str, Any]) -> None:
        for file in said.get("files", []):
            self.keep(file)
        if self.json:
            print(json.dumps(said, ensure_ascii=False), flush=True)
        else:
            print(self.text_of(said), flush=True)

    def keep(self, file: dict[str, Any]) -> None:
        """Save the file, if it came with its contents and a folder is given,
        and say where in their place. Raises Refused."""
        if self.save is None or "base64" not in file:
            return
        name = Path(file["filename"] or "nejomibot")
        suffix = name.suffix or mimetypes.guess_extension(file["content_type"])
        try:
            # A name of its own, readable by this user alone
            handle, path = tempfile.mkstemp(
                suffix=suffix or ".bin", prefix=f"{name.stem}-", dir=self.save
            )
            with os.fdopen(handle, "wb") as saved:
                saved.write(base64.b64decode(file.pop("base64")))
        except OSError as e:
            raise Refused(f"Can't save to {self.save}: {e.strerror or e}") from e
        file["saved"] = path

    def text_of(self, said: dict[str, Any]) -> str:
        """An answer: its text, then its files; or a message the bot
        received: when, where and from whom, then its text and files."""
        lines = [self.styles(said["text"], said["styles"])] if said["text"] else []
        lines += [f"📎 {file_text(file)}" for file in said["files"]]
        if "at" not in said:
            return "\n".join(lines)
        if not said["files"] and (count := said["attachments"]):
            lines.append(f"📎 {count} attachment{'s' * (count > 1)}")
        at = datetime.fromisoformat(said["at"])
        where = f"👥 {said['chat_name']} · " if said["chat"] else "👤 "
        edited = " ✏️" if said["edited"] else ""
        body = "\n".join(lines).replace("\n", "\n  ")
        return f"{at:%Y-%m-%d %H:%M} {where}{said['sender_name']}{edited}\n  {body}"

    def styles(self, text: str, styles: list[dict[str, Any]]) -> str:
        """The text, with its styles as the terminal shows them, if it does."""
        if not self.styled or not styles:
            return text
        codes: list[set[str]] = [set() for _ in text]
        for style in styles:
            if code := ANSI.get(style["style"]):
                end = min(style["start"] + style["length"], len(text))
                for i in range(style["start"], end):
                    codes[i].add(code)
        out: list[str] = []
        now: set[str] = set()
        for char, here in zip(text, codes, strict=True):
            if here != now:
                out.append(f"\x1b[0;{';'.join(sorted(here))}m" if here else "\x1b[0m")
                now = here
            out.append(char)
        return "".join(out) + ("\x1b[0m" if now else "")


def file_text(file: dict[str, Any]) -> str:
    """E.g. 'IMG_1234.jpg, image/jpeg, 1.2 MB', or where it was saved."""
    if "saved" in file:
        return file["saved"]
    parts = [part for part in (file["filename"], file["content_type"]) if part]
    if file["size"] is not None:
        parts.append(size_text(file["size"]))
    shown = ", ".join(parts)
    if file.get("missing"):
        return f"{shown}: signal-cli no longer has it"
    if file.get("too_big"):
        return f"{shown}: too big to fetch through the bot"
    return shown


def talk(output: Output, text: str, files: Sequence[File] = ()) -> None:
    """Send the bot the message, with the files, and show its answers.
    Raises Refused."""
    request = {"text": text, "attachments": [file.header for file in files]}
    answered = False
    for said in exchange(request, files):
        if answered and not output.json:
            print()  # between answers, as between bubbles
        output.show(said)
        answered = True
    if not answered:
        print("No answer.", file=sys.stderr)


def read_message() -> str:
    """A message typed in the terminal: a line, and the next, too, while one
    ends in a \\. Raises EOFError at the end."""
    lines = [input("> ")]
    while lines[-1].endswith("\\"):
        lines[-1] = lines[-1][:-1]
        lines.append(input("... "))
    return "\n".join(lines)


def chat(output: Output) -> None:
    """A chat in the terminal, a message a line, until Ctrl-D."""
    with contextlib.suppress(ImportError):
        # Line editing and history, as in a shell
        import readline  # noqa: F401  # pyright: ignore[reportUnusedImport]
    print("A chat with the bot, as its first admin. Ctrl-D ends it.", file=sys.stderr)
    while True:
        try:
            text = read_message()
        except EOFError:
            print(file=sys.stderr)
            return
        if text.strip():
            try:
                talk(output, text)
            except Refused as e:
                print(f"nejomibot-chat: {e}", file=sys.stderr)


def received(output: Output, recent: int | None, follow: bool) -> None:
    """The latest messages the bot received, oldest first, then, to follow
    them, each as it comes. Raises Refused, also once the bot stops, while
    following."""
    request = {"recent": recent, "follow": follow, "files": output.save is not None}
    shown = False
    for said in exchange(request, timeout=None if follow else ANSWER_TIMEOUT):
        output.show(said)
        shown = True
    if follow:
        raise Refused("The bot has stopped.")
    if not shown:
        print("No messages received since the bot started.", file=sys.stderr)


def positive(text: str) -> int:
    if not text.isdecimal() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"not a number of messages: {text}")
    return int(text)


def folder(text: str) -> Path:
    if not Path(text).is_dir():
        raise argparse.ArgumentTypeError(f"no such folder: {text}")
    return Path(text)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nejomibot-chat",
        description="Use the bot from a terminal, as its first admin does in "
        "a direct chat with it. Its answers come here; what posts to other "
        "chats, as /msg does, posts there.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="the message, such as /weather; without it, standard input, or "
        "in a terminal, a chat: a line a message, one that ends in \\ going on "
        "in the next",
    )
    parser.add_argument(
        "-a",
        "--attach",
        action="append",
        default=[],
        metavar="FILE",
        help="attach FILE, again for more; - reads standard input: a file, or "
        "the files in a tar archive; 25 MB together at most",
    )
    parser.add_argument(
        "--to",
        metavar="CHATS",
        help="post the message to these chats, numbers from /chats such as "
        "1,2, as /msg does",
    )
    parser.add_argument(
        "-r",
        "--recent",
        nargs="?",
        const=RECENT,
        type=positive,
        metavar="N",
        help=f"the latest N messages the bot received, in any chat; without "
        f"N, all it keeps, the latest {RECENT}",
    )
    parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="the messages the bot receives, in any chat, as they come, until Ctrl-C",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print what the bot says as JSON, an object a line",
    )
    parser.add_argument(
        "--save",
        metavar="DIR",
        type=folder,
        help="save the files in what the bot says to DIR",
    )
    args = parser.parse_args()
    if (args.recent or args.follow) and (args.message or args.attach or args.to):
        parser.error("--recent and --follow take no message")
    if args.to is not None and not CHATS.match(args.to):
        parser.error("--to takes numbers from /chats, such as 1,2")
    if args.attach.count("-") > 1:
        parser.error("standard input can be attached only once")
    return args


def run(args: argparse.Namespace, output: Output) -> None:
    """Raises Refused."""
    if args.recent or args.follow:
        received(output, args.recent, args.follow)
        return
    files = read_files(args.attach)
    text = " ".join(args.message)
    if not text and "-" not in args.attach:
        if not sys.stdin.isatty():
            text = sys.stdin.read()
        elif args.to:
            print("Type the message, then Ctrl-D.", file=sys.stderr)
            text = sys.stdin.read()
        elif not files:
            chat(output)
            return
    text = text.rstrip("\n")
    if not text.strip() and not files:
        raise Refused(
            "No message: give one, send one to standard input, or for a chat, "
            "run it in a terminal (podman exec -it)."
        )
    if args.to:
        text = f"/msg {args.to} {text}".rstrip()
    talk(output, text, files)


def main() -> None:
    args = arguments()
    styled = not args.json and shows_styles()
    try:
        run(args, Output(json=args.json, save=args.save, styled=styled))
    except Refused as e:
        sys.exit(f"nejomibot-chat: {e}")
    except KeyboardInterrupt:
        print(file=sys.stderr)
        sys.exit(130)
    except BrokenPipeError:
        # Standard output went, as with | head: nothing more is said there
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
