import base64
import io
import sys
import tarfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from nejomibot import chat_cli
from nejomibot.chat_cli import File, Output, Refused, content_type, read_file

JPEG = b"\xff\xd8\xff\xe0" + bytes(20)


def stdin(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    """Standard input, as from a pipe."""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))


def tar_of(files: dict[str, bytes]) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        folder = tarfile.TarInfo("photos")
        folder.type = tarfile.DIRTYPE  # not a file
        tar.addfile(folder)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return archive.getvalue()


@pytest.mark.parametrize(
    ("data", "name", "kind"),
    [
        (JPEG, "", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nxx", "", "image/png"),
        (b"\0\0\0\x18ftypheic", "", "image/heic"),
        (b"\0\0\0\x18ftypisom", "", "video/mp4"),
        (b"RIFF\0\0\0\0WEBPVP8", "", "image/webp"),
        (b"hello", "", chat_cli.UNKNOWN),
        (b"hello", "notes.txt", "text/plain"),
        (JPEG, "clip.mov", "video/quicktime"),
    ],
)
def test_content_type(data: bytes, name: str, kind: str) -> None:
    assert content_type(data, name) == kind


def test_a_file(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(JPEG)
    [file] = read_file(str(tmp_path / "a.jpg"))
    assert file == File("a.jpg", JPEG)
    header = {"filename": "a.jpg", "content_type": "image/jpeg", "size": 24}
    assert file.header == header


def test_a_file_that_isnt_there(tmp_path: Path) -> None:
    with pytest.raises(Refused, match=r"Can't read .*: No such file"):
        read_file(str(tmp_path / "gone.jpg"))


def test_a_file_too_big(tmp_path: Path) -> None:
    with (tmp_path / "big.mp4").open("wb") as big:
        big.truncate(chat_cli.MAX_ATTACHED + 1)  # no disk, as it's sparse
    with pytest.raises(Refused, match="over 25 MB"):
        read_file(str(tmp_path / "big.mp4"))


def test_files_too_big_together(tmp_path: Path) -> None:
    for name in ("a.mp4", "b.mp4"):
        with (tmp_path / name).open("wb") as each:
            each.truncate(chat_cli.MAX_ATTACHED // 2 + 1)
    with pytest.raises(Refused, match="together, over 25 MB"):
        chat_cli.read_files([str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")])


def test_a_file_on_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin(monkeypatch, JPEG)
    assert read_file("-") == [File("", JPEG)]


def test_files_in_a_tar_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin(monkeypatch, tar_of({"photos/a.jpg": JPEG, "b.png": b"png"}))
    assert read_file("-") == [File("a.jpg", JPEG), File("b.png", b"png")]


def test_styles_in_a_terminal() -> None:
    styles = [
        {"start": 0, "length": 2, "style": "BOLD"},
        {"start": 1, "length": 3, "style": "ITALIC"},
        {"start": 5, "length": 2, "style": "MONOSPACE"},  # as it is
    ]
    text = Output(styled=True).styles("Hi there", styles)
    assert text == "\x1b[0;1mH\x1b[0;1;3mi\x1b[0;3m t\x1b[0mhere"
    assert Output().styles("Hi there", styles) == "Hi there"


def test_an_answer() -> None:
    said = {
        "text": "Photo",
        "styles": [],
        "files": [
            {"content_type": "image/jpeg", "filename": "", "size": 1_234_567},
        ],
    }
    assert Output().text_of(said) == "Photo\n📎 image/jpeg, 1.23 MB"


def received(**fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "at": "2026-10-24T08:14:05+02:00",
        "chat": "group.ZmFtaWx5",
        "chat_name": "Familjen",
        "sender": "a11ce000-0000-4000-8000-000000000001",
        "sender_name": "Alice (+46700000001)",
        "text": "Hej!\nVem?",
        "styles": [],
        "attachments": 0,
        "files": [],
        "edited": False,
    }
    return entry | fields


def test_a_message_received() -> None:
    assert Output().text_of(received()) == (
        "2026-10-24 08:14 👥 Familjen · Alice (+46700000001)\n  Hej!\n  Vem?"
    )
    shown = Output().text_of(received(chat=None, attachments=2, edited=True))
    assert shown.splitlines() == [
        "2026-10-24 08:14 👤 Alice (+46700000001) ✏️",
        "  Hej!",
        "  Vem?",
        "  📎 2 attachments",
    ]
    missing = {"content_type": "video/mp4", "filename": "a.mp4", "size": None}
    shown = Output().text_of(received(files=[missing | {"missing": True}]))
    assert shown.endswith("\n  📎 a.mp4, video/mp4: signal-cli no longer has it")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "saved").mkdir()
    return tmp_path / "saved"


def test_save(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    content = base64.b64encode(JPEG).decode()
    file = {"content_type": "image/jpeg", "filename": "", "size": 24}
    Output(save=folder).show({"text": "", "styles": [], "files": [
        file | {"base64": content}
    ]})  # fmt: skip
    [saved] = folder.iterdir()
    assert saved.name.startswith("nejomibot-") and saved.suffix == ".jpg"
    assert saved.read_bytes() == JPEG
    assert saved.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr().out == f"📎 {saved}\n"


def test_save_as_json(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    content = base64.b64encode(JPEG).decode()
    file = {"content_type": "image/jpeg", "filename": "IMG_1.jpg", "size": 24}
    Output(json=True, save=folder).show(received(files=[file | {"base64": content}]))
    [saved] = folder.iterdir()
    assert saved.name.startswith("IMG_1-")
    # Where it is, in place of what's in it
    assert f'"saved": "{saved}"' in capsys.readouterr().out


class Talks:
    """What nejomibot-chat would send the bot."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[tuple[str, list[File]]] = []
        monkeypatch.setattr(chat_cli, "talk", self.talk)

    def talk(self, output: Output, text: str, files: Sequence[File] = ()) -> None:
        self.sent.append((text, list(files)))


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["nejomibot-chat", *args])
    chat_cli.run(chat_cli.arguments(), Output())


def test_the_message_given(monkeypatch: pytest.MonkeyPatch) -> None:
    talks = Talks(monkeypatch)
    stdin(monkeypatch, b"")
    run(monkeypatch, "/weather", "Helsinki")
    assert talks.sent == [("/weather Helsinki", [])]


def test_the_message_on_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    talks = Talks(monkeypatch)
    stdin(monkeypatch, b"Dinner at six\nor seven\n")
    run(monkeypatch, "--to", "1,2")
    assert talks.sent == [("/msg 1,2 Dinner at six\nor seven", [])]


def test_files_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    talks = Talks(monkeypatch)
    stdin(monkeypatch, JPEG)
    run(monkeypatch, "-a", "-", "--to", "3")
    assert talks.sent == [("/msg 3", [File("", JPEG)])]


class Terminal(io.StringIO):
    """A terminal, as standard input or output."""

    def isatty(self) -> bool:
        return True


def test_a_chat_with_chats_in_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    chats: list[list[int]] = []

    def connected(output: Output, wanted: list[int]) -> None:
        chats.append(wanted)

    monkeypatch.setattr(chat_cli, "connected", connected)
    monkeypatch.setattr(sys, "stdin", Terminal())
    run(monkeypatch, "--to", "1,3")
    assert chats == [[1, 3]]


def test_files_to_chats_from_a_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With files, the terminal gives the one message to post with them
    talks = Talks(monkeypatch)
    photo = tmp_path / "a.jpg"
    photo.write_bytes(JPEG)
    monkeypatch.setattr(sys, "stdin", Terminal("Look!\n"))
    run(monkeypatch, "-a", str(photo), "--to", "1")
    assert talks.sent == [("/msg 1 Look!", [File("a.jpg", JPEG)])]


def test_recent_in_some_chats(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    asked: list[dict[str, Any]] = []

    def exchange(
        request: dict[str, Any], files: Sequence[File] = (), timeout: float | None = 0
    ) -> Iterator[dict[str, Any]]:
        asked.append(request)
        yield {"chats": [{"name": "Familjen", "group": True}], "recent": 1}
        yield received()

    monkeypatch.setattr(chat_cli, "exchange", exchange)
    run(monkeypatch, "--recent", "5", "--to", "1")
    assert asked == [{"recent": 5, "follow": False, "files": False, "chats": [1]}]
    # Without the chats' names, which only a chat with them shows
    assert capsys.readouterr().out == Output().text_of(received()) + "\n"


def test_shown_above_the_line_being_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    screen = chat_cli.Screen()
    screen.line = lambda: "Dinner at"
    screen.prompt, screen.typing = "> ", True
    shown = Terminal()
    monkeypatch.setattr(sys, "stdout", shown)
    screen.show("Alice: Hej!")
    # Over the prompt's line, then the prompt and what's typed again
    assert shown.getvalue() == "\r\x1b[KAlice: Hej!\n> Dinner at"
    screen.typing = False
    screen.show("Bob: Hi")
    assert shown.getvalue().endswith("> Dinner atBob: Hi\n")
    screen.close()


def test_no_message(monkeypatch: pytest.MonkeyPatch) -> None:
    Talks(monkeypatch)
    stdin(monkeypatch, b"\n")
    with pytest.raises(Refused, match="No message"):
        run(monkeypatch)


@pytest.mark.parametrize(
    "args",
    [
        ["--recent", "5", "/ping"],
        ["--follow", "-a", "x.jpg"],
        ["--follow", "--to", "1,x"],
        ["--to", "1, 2", "Hi"],
        ["--to", "Alice", "Hi"],
        ["-a", "-", "-a", "-", "/msg 1"],
        ["--recent", "0"],
        ["--save", "/no/such/folder", "/photo"],
    ],
)
def test_wrong_arguments(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["nejomibot-chat", *args])
    with pytest.raises(SystemExit) as stopped:
        chat_cli.arguments()
    assert stopped.value.code == 2


def test_no_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing listens on the test's socket
    monkeypatch.setattr(sys, "argv", ["nejomibot-chat", "/ping"])
    with pytest.raises(SystemExit, match=r"doesn't answer .*: it isn't running"):
        chat_cli.main()
