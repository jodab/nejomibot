"""nejomibot-account: the bot's Signal account in signal-cli-rest-api, from a
terminal: registering a number, restoring an account with its Recovery key
or linking to a phone, the profile, the
username, the PIN and privacy, the linked devices, the safety numbers and
rate limits. HELP below says how.

It asks signal-cli-rest-api itself, one request at a time, through the
standard library, as signalbot does none of this (rest.py has what the bot
itself asks): it runs without the bot, and without the bot's settings, of
which it reads only where signal-cli-rest-api is, the account, and data_dir,
from the NEJOMIBOT_ variables or the config file, as the bot does. What it
changes in the profile goes in data_dir/bot.txt too, through the bot's own
code (profile.py), which also makes avatars as the bot's /avatar does: the
bot changes what differs from bot.txt at each start.
"""

import argparse
import base64
import contextlib
import http.client
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast
from urllib.parse import quote, urlencode

from .config import (
    ABOUT_MAX_BYTES,
    ABOUT_MAX_CHARACTERS,
    NAME_MAX_BYTES,
    PHONE_NUMBER,
    SIGNAL_ID,
    USERNAME,
    config_file,
)

if TYPE_CHECKING:
    from .files import KeptLines
    from .profile import AvatarImage

PROG = "nejomibot-account"
DEFAULT_SERVICE = "127.0.0.1:8080"  # signal-cli-rest-api's own default port
DEFAULT_DEVICE = "nejomibot"  # how a linked signal-cli shows on the phone
DEFAULT_DATA = "/data"  # data_dir's default, as in config.py
TIMEOUT = 30  # seconds for most requests
SLOW_TIMEOUT = 120  # for those that wait on Signal's servers
LINK_WAIT = 180  # seconds to wait for the QR code to be scanned
LINK_POLL = 3  # seconds between looks for the linked account
SMS_WAIT = 60  # seconds Signal wants before it calls with the code
# The biggest picture the tool reads, as the bot's /avatar takes, and the
# biggest avatar Signal's Android app fetches
PICTURE_MAX_BYTES = 30 * 1024 * 1024
AVATAR_MAX_BYTES = 10 * 1024 * 1024
REGISTRATION_CAPTCHA = "https://signalcaptchas.org/registration/generate.html"
CHALLENGE_CAPTCHA = "https://signalcaptchas.org/challenge/generate.html"
CAPTCHA_START = "signalcaptcha://"
RECOVERY_KEY_LENGTH = 64  # letters and digits, as Signal keeps it
# A link to a device to link, from its QR code: sgnl://linkdevice?..., or
# tsdevice:... from older apps
DEVICE_LINK = ("sgnl://linkdevice?", "tsdevice:")
EVERYONE = frozenset({"everyone", "yes", "true", "on"})
NOBODY = frozenset({"nobody", "no", "false", "off"})
STATUSES = {
    "TRUSTED_VERIFIED": "verified",
    "TRUSTED_UNVERIFIED": "trusted, not verified",
    "UNTRUSTED": "UNTRUSTED: changed, and not trusted yet",
}
# No proxy: signal-cli-rest-api is beside the bot, and a proxy in the
# environment, as for the Internet, isn't for it
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

HELP = f"""\
{PROG}: set up and look after the bot's Signal account in signal-cli-rest-api.

Everything signal-cli-rest-api can do with the account itself: register a
number, restore or link, the profile (name, About, avatar), username, PIN,
privacy, linked devices, safety numbers and rate limits. It only talks to the
REST API, one request at a time, explains what Signal answers, and asks
before anything that can't be undone.

Usage: {PROG} [options] [COMMAND [ARGS...]]

Setting up
  setup                      guided: register, restore or link, then the
                             profile, username, PIN and privacy, each one
                             skippable
  register [--voice] [--captcha LINK]
                             have Signal send a verification code by SMS, or
                             call with it (--voice); walks through a captcha
                             if Signal wants one, then asks for the code,
                             and has it sent again if none comes
  verify CODE [--pin]        finish registering with the code; --pin asks for
                             the PIN of a number with a registration lock
  restore [--key-file FILE] [--totp CODE]
                             restore an account by its Signal ID, as one
                             without a number is, with its Recovery key,
                             typed in unseen or read from FILE (see RESTORE
                             below)
  link [NAME]              make signal-cli a linked device of a phone,
                             called NAME there (default {DEFAULT_DEVICE}), to use
                             its account: shows a QR code to scan, and
                             waits for it (see LINKED below)

The account
  status                     the account and the REST API (the default)
  profile                    show the profile
  profile [--name NAME] [--about TEXT | --no-about]
          [--avatar FILE | --no-avatar]
                             change it; whatever isn't given stays as it is.
                             --avatar - takes the picture from standard
                             input (see In the bot's container, below)
  username [NAME | --remove] show, set or remove the username; Signal adds a
                             number to NAME unless it has one, like name.42
  pin [--remove]             set the registration lock PIN (asked for, so it
                             stays out of the shell history), or remove it
  privacy [--number-seen-by everyone|nobody]
          [--findable-by-number everyone|nobody]
                             who sees the phone number, and who can find the
                             account by it (an account with a number)
  rate-limit TOKEN [CAPTCHA] lift a rate limit by solving a captcha, for
                             the challenge TOKEN Signal gave with it
  rate-limit --to WHO        send WHO (a phone number, Signal ID or
                             u:username) a short test message;
                             if Signal rate-limits the account, it gives a
                             challenge, and the captcha comes next. The bot
                             logs when Signal rate-limits it, but signalbot
                             doesn't pass the challenge on.
  unregister [--delete-account] [--delete-local-data]
                             stop using the account in signal-cli; with
                             --delete-account, delete the Signal account too
  delete-local-data [--even-if-registered]
                             delete what signal-cli keeps of an account that
                             is no longer registered or linked

Devices
  devices                    list the linked devices
  devices add LINK           link another device to this account, with the
                             sgnl://linkdevice?... link in its QR code
  devices remove ID          unlink a device
  devices sync               send the contact list to the linked devices

Safety numbers
  identities                 everyone's safety number, and whether verified
  trust WHO SAFETY_NUMBER    verify WHO's safety number (60 digits), once
                             compared with the one on their phone, as the
                             bot's /trust does
  trust WHO --unverified     accept WHO's keys as they are, without verifying
                             them: after a safety number changed, signal-cli
                             sends to them again, but they aren't verified
                             (WHO is a phone number or ID, as identities shows)

The REST API
  accounts                   the accounts registered in signal-cli
  search NUMBER...           which phone numbers are on Signal
  about                      its version and mode
  log-level [debug|info|warn]
                             show or set how much it logs
  trust-mode [always|on-first-use|never]
                             show or set when new safety numbers are trusted
                             (in json-rpc mode, only the container sets it)

Options, before or after the command
  -u, --url URL              signal-cli-rest-api; default: signal_service in
                             the bot's settings, else {DEFAULT_SERVICE}
  -a, --account ACCOUNT      the account: its phone number, or its Signal
                             ID; default: account in the bot's settings, else
                             the only one registered
  -c, --config FILE          the bot's config; default: $NEJOMIBOT_CONFIG
                             (/data/config.toml in the bot's container), else
                             config.toml here
  -y, --yes                  don't ask, not even before what can't be undone
  -n, --dry-run              show the request that would change something,
                             and stop there
  -j, --json                 print what the API answers, as JSON
  -v, --verbose              show every request (PINs, keys and captchas
                             hidden)
  -h, --help                 show this help

Examples
  {PROG}                                  # status
  {PROG} setup
  {PROG} profile --about "Weather and photos" --avatar logo.png
  {PROG} username mybot

In the bot's container
  The image includes the tool, which takes signal-cli-rest-api's address
  and the account from the bot's settings:
    podman exec -it nejomibot {PROG} setup
  Without a running bot, in a container of its own on signal-cli-rest-api's
  network (127.0.0.1:8080; setup asks for the number):
    podman run --rm -it --no-healthcheck --network container:signal \\
      docker.io/jodab/nejomibot {PROG} setup
  With Compose: docker compose exec nejomibot ..., or without a running bot,
  docker compose run --rm nejomibot ...
  An avatar comes from standard input, with --avatar - and -i (not -it):
    podman exec -i nejomibot {PROG} profile --avatar - < logo.png
  Without a terminal, questions stop the tool; --yes answers them. Outside
  a container, run uv run {PROG} in the bot's folder.

Avatars are made as the bot's /avatar makes them: upright, cropped to their
middle square, at most 1024x1024, without metadata. Linking shows its QR code
in the terminal, and a captcha page opens in the browser, if there is one.

signal-cli-rest-api can't set the family name or the emoji before About: a
family name stays after a new --name.

The bot keeps its profile in bot.txt in its data folder, and at each start
changes what differs from it: where that folder is, as in the bot's
container, what the tool changes in the profile goes there too.

RESTORE: signal-cli becomes the account's primary device, so wherever it was
that before, a phone or another signal-cli, it stops working. It takes a
signal-cli-rest-api whose register takes a recovery_key, which no release
has yet. If Signal wants a TOTP code too, restore asks for it, or takes
--totp.

LINKED: linked to a phone, the bot uses the phone's account, which stays
there. It needs no number of its own, and it's the other way to use an
account without a number, as Signal Login creates (see the README).
The phone has to come online at least once every 30 days, or Signal
unlinks the bot, and only the phone can link it again, set the PIN or link
other devices. What is typed on the phone in a direct chat reaches the bot
as if the other person sent it (signalbot can't tell them apart), so a
command typed there acts as theirs, and in a chat with an admin, as the
admin's. A phone kept for the bot avoids that.
"""


class Stop(Exception):
    """Why the tool stops: it says so as an error, and exits 1."""


class Wrong(Exception):
    """A command given wrong: said as an error, with a pointer to --help, and
    the tool exits 2."""


# Output


def info(text: str = "") -> None:
    print(text, flush=True)


def warn(text: str) -> None:
    print(f"WARNING: {text}", file=sys.stderr, flush=True)


def error(text: str) -> None:
    print(f"ERROR: {text}", file=sys.stderr, flush=True)


def say(text: str) -> None:
    """A paragraph, its lines as long as a terminal's."""
    info(textwrap.fill(text, 78, break_long_words=False, break_on_hyphens=False))


def row(title: str, text: str) -> None:
    """A line of a table."""
    info(f"{title:<12} {text}")


def step(text: str) -> None:
    """A heading for a step of setup."""
    info(f"\n== {text}")


def as_json(found: Any) -> str:
    return json.dumps(found, indent=2, ensure_ascii=False)


# Checks


def is_number(text: str) -> bool:
    return bool(re.fullmatch(PHONE_NUMBER, text, re.ASCII))


def is_signal_id(text: str) -> bool:
    return bool(re.fullmatch(SIGNAL_ID, text, re.ASCII))


def normal_account(text: str) -> str:
    """An account as signal-cli knows it: a Signal ID in lower case, its
    dashes put in if it has none."""
    account = text.strip().lower()
    if re.fullmatch(r"[0-9a-f]{32}", account, re.ASCII):
        parts = (
            account[:8],
            account[8:12],
            account[12:16],
            account[16:20],
            account[20:],
        )
        account = "-".join(parts)
    return account


def six_digits(code: str, what: str) -> str:
    """The code's digits, as Signal shows them, like 123-456. Raises Stop."""
    digits = "".join(each for each in code if each in "0123456789")
    if len(digits) != 6:
        raise Stop(f"{what} has 6 digits, like 123-456.")
    return digits


def stored_key(text: str) -> str:
    """A Recovery key as Signal keeps it, in lower case, read as Signal
    Android reads one back from the form it shows: in upper case, with # for
    O and = for 0, in groups. Raises Stop."""
    key = text.replace("#", "o").replace("=", "0").lower()
    key = re.sub(r"[^0-9a-z]", "", key)
    if len(key) != RECOVERY_KEY_LENGTH:
        raise Stop(
            f"A Recovery key has {RECOVERY_KEY_LENGTH} letters and digits, and that "
            f"has {len(key)}."
        )
    return key


def utf8(text: str, what: str) -> str:
    """The text, if UTF-8 can carry it, as Signal does; not bytes that came
    in as something else."""
    try:
        text.encode()
    except UnicodeEncodeError as e:
        raise Stop(f"{what} isn't text in UTF-8.") from e
    return text


def check_name(name: str) -> None:
    if (size := len(utf8(name, "The name").encode())) > NAME_MAX_BYTES:
        raise Stop(
            f"A name holds at most {NAME_MAX_BYTES} bytes in Signal, and that's "
            f"{size} (å, ä and ö take two each, emoji four)."
        )


def check_about(about: str) -> None:
    if (count := len(utf8(about, "About"))) > ABOUT_MAX_CHARACTERS:
        raise Stop(
            f"About holds at most {ABOUT_MAX_CHARACTERS} characters in Signal's "
            f"apps, and that's {count}."
        )
    if (size := len(about.encode())) > ABOUT_MAX_BYTES:
        raise Stop(
            f"About holds at most {ABOUT_MAX_BYTES} bytes in Signal, and that's {size}."
        )


def everyone_or_nobody(word: str) -> bool | None:
    """True for everyone, False for nobody; None for neither."""
    if word.lower() in EVERYONE:
        return True
    if word.lower() in NOBODY:
        return False
    return None


def path_part(text: str) -> str:
    """The text as a part of a URL's path."""
    return quote(text, safe="")


def service_url(address: str) -> str:
    url = (
        address if address.startswith(("http://", "https://")) else f"http://{address}"
    )
    return url.rstrip("/")


# The bot's settings, as far as the tool needs them


class Settings:
    """Where signal-cli-rest-api is, the account and data_dir, as the bot has
    them: from their NEJOMIBOT_ variables, else from the config file, read
    loosely: the bot itself reads it strictly, and stops on what's wrong in
    it, but the account may well be set up before the rest is."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.table: dict[str, Any] = {}
        try:
            with path.open("rb") as f:
                self.table = tomllib.load(f)
        except FileNotFoundError:
            pass
        except (OSError, tomllib.TOMLDecodeError) as e:
            warn(f"Can't read the bot's config {path} ({e}): going on without it.")

    def file_value(self, name: str) -> str:
        value = self.table.get(name)
        return value.strip() if isinstance(value, str) else ""

    def value(self, name: str) -> str:
        """The setting, from its variable or the file; "" if neither has it."""
        from_env = os.environ.get(f"NEJOMIBOT_{name.upper()}", "").strip()
        return from_env or self.file_value(name)


# Talking to signal-cli-rest-api

type Object = dict[str, Any]  # a JSON object


def text(found: Any) -> str:
    """The JSON string; empty if found is something else."""
    return found if isinstance(found, str) else ""


def as_object(found: Any) -> Object:
    """The JSON object; an empty one if found is something else."""
    return cast("Object", found) if isinstance(found, dict) else {}


def objects(found: Any) -> list[Object]:
    """The JSON objects in the list found, if it is one."""
    if not isinstance(found, list):
        return []
    return [
        cast("Object", each)
        for each in cast("list[Any]", found)
        if isinstance(each, dict)
    ]


@dataclass(frozen=True)
class Answer:
    """signal-cli-rest-api's answer: its HTTP status, and body."""

    status: int
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        """The body's JSON; None for an empty body. Raises Stop."""
        if not self.body.strip():
            return None
        try:
            return json.loads(self.body)
        except ValueError as e:
            start = self.body[:80].decode(errors="replace")
            raise Stop(f"signal-cli-rest-api's answer isn't JSON: {start}") from e

    def object(self) -> Object:
        """The body, as the object it should be; empty if it isn't one."""
        return as_object(self.json())

    def list(self) -> list[Any]:
        """The body, as the list it should be; empty if it isn't one."""
        found = self.json()
        return cast("list[Any]", found) if isinstance(found, list) else []

    def error(self) -> str:
        """What went wrong, as signal-cli-rest-api says: its error, or else
        the start of its answer."""
        text = self.body.decode(errors="replace")
        with contextlib.suppress(ValueError):
            if said := as_object(json.loads(text)).get("error"):
                return str(said)
        return text[:300].replace("\n", " ").strip() or "no reason given"


def shown(body: dict[str, Any]) -> str:
    """A request body as --verbose and --dry-run show it: secrets hidden, an
    avatar summed up."""
    hidden = {
        key: "(hidden)"
        if key in ("pin", "captcha", "recovery_key", "totp")
        else f"({len(value)} characters)"
        if key == "base64_avatar"
        else value
        for key, value in body.items()
    }
    return json.dumps(hidden, ensure_ascii=False, separators=(",", ":"))


def why_not(error: BaseException) -> str:
    """Why a request had no answer, in a few words."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, OSError) and reason.strerror:
        return reason.strerror
    return str(reason) or type(reason).__name__


def couldnt_connect(error: BaseException) -> bool:
    """Whether the request never got there: nothing listens, or no such host."""
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, ConnectionRefusedError | socket.gaierror)


# Asking


def interactive() -> bool:
    return sys.stdin.isatty()


def read_line(prompt: str) -> str:
    """A line typed in, after the prompt. Raises Stop at the end of input."""
    try:
        if sys.stdout.isatty():
            # So that line editing knows where the line starts
            return input(prompt)
        # Not with what's printed, as JSON may be
        print(prompt, end="", file=sys.stderr, flush=True)
        return input()
    except EOFError:
        print(file=sys.stderr)
        raise Stop("No answer, so stopped.") from None


def open_page(url: str) -> None:
    """Open the page in the browser, if there's one to open it in. Never
    raises: the page is said to be opened all the same."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return
    if (opener := shutil.which("xdg-open")) is None:
        return
    with contextlib.suppress(OSError):
        subprocess.Popen(
            [opener, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def countdown(seconds: int) -> None:
    """Wait, showing how long is left."""
    for left in range(seconds, 0, -1):
        print(f"\rWaiting {left:3d} s ", end="", file=sys.stderr, flush=True)
        time.sleep(1)
    print(f"\r{'':20}\r", end="", file=sys.stderr, flush=True)


def qr_code(text: str) -> str:
    """The text as a QR code for a terminal, two rows to a line, in black on
    white whatever the terminal's colors are, with the quiet zone round it
    that a scanner needs, as qrencode's ansiutf8 draws one."""
    import segno  # here alone: linking is all that needs it

    matrix = segno.make_qr(text).matrix_iter(border=4)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    rows: list[list[bool]] = [[bool(cell) for cell in each] for each in matrix]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if len(rows) % 2:
        rows.append([False] * len(rows[0]))
    lines: list[str] = []
    for top, bottom in zip(rows[::2], rows[1::2], strict=True):
        cells = [
            f"\x1b[{30 if upper else 97};{40 if lower else 107}m▀"
            for upper, lower in zip(top, bottom, strict=True)
        ]
        lines.append("".join(cells) + "\x1b[0m")
    return "\n".join(lines)


def picture(given: str) -> bytes:
    """The picture in the file, or with -, from standard input. Raises Stop."""
    if given == "-":
        if sys.stdin.isatty():
            raise Stop(
                f"--avatar - takes the picture from standard input, as in: podman "
                f"exec -i nejomibot {PROG} profile --avatar - < logo.png (-i, not -it)"
            )
        data = sys.stdin.buffer.read(PICTURE_MAX_BYTES + 1)
        if not data:
            raise Stop("No picture came on standard input")
    else:
        try:
            with Path(given).expanduser().open("rb") as f:
                data = f.read(PICTURE_MAX_BYTES + 1)
        except OSError as e:
            raise Stop(
                f"Can't read the picture {given}: {e.strerror or e}. In the bot's "
                "container, which can't see your files, pipe it in with --avatar - "
                "(see --help)."
            ) from e
    if len(data) > PICTURE_MAX_BYTES:
        raise Stop(
            f"The picture is over {PICTURE_MAX_BYTES // 1024 // 1024} MB, too big "
            "for an avatar."
        )
    return data


@dataclass
class Options:
    url: str | None = None
    account: str | None = None
    config: Path | None = None
    yes: bool = False
    dry_run: bool = False
    json: bool = False
    verbose: bool = False


class Tool:
    """The tool at work: its options, signal-cli-rest-api, and the account."""

    def __init__(self, options: Options) -> None:
        self.options = options
        self.settings = Settings(options.config or config_file())
        given = options.url or self.settings.value("signal_service") or DEFAULT_SERVICE
        self.url = service_url(given)
        self.account = options.account or ""
        self.account_path = ""  # the account, as a part of a URL
        self.number = ""  # its phone number, if any, once is_registered has it
        self.account_id = ""  # and its Signal ID
        self.accounts: list[str] = []  # in signal-cli, each by number, else ID
        self.pairs: list[tuple[str, str]] = []  # and their numbers and IDs
        self.me: dict[str, Any] = {}  # the account's own entry, from read_me
        self.about: dict[str, Any] = {}  # signal-cli-rest-api's, from read_about

    # Saying, and asking

    def detail(self, text: str) -> None:
        """What --verbose shows."""
        if self.options.verbose:
            print(text, file=sys.stderr, flush=True)

    def ask(self, question: str, default: str = "") -> str:
        """A line typed in; empty means the default."""
        if not interactive():
            raise Stop(
                f'"{question}" needs an answer, but there\'s no terminal to ask on.'
            )
        prompt = f"{question} [{default}] " if default else f"{question} "
        return read_line(prompt) or default

    def ask_secret(self, question: str) -> str:
        """A line typed in, without showing it."""
        if not interactive():
            raise Stop(f'"{question}" has to be typed in, but there\'s no terminal.')
        try:
            return getpass(f"{question} ")
        except EOFError:
            print(file=sys.stderr)
            raise Stop("No answer, so stopped.") from None

    def confirm(self, question: str) -> bool:
        """Whether the answer is yes; --yes answers yes, and without a terminal
        to ask on, it stops."""
        if self.options.yes:
            self.detail(f"{question} yes (--yes)")
            return True
        if not interactive():
            raise Stop(
                f"{question} There's no terminal to ask on: give --yes to go ahead."
            )
        try:
            answer = read_line(f"{question} [y/N] ")
        except Stop:
            return False
        return answer.strip().lower() in ("y", "yes")

    def confirm_typed(self, warning: str, word: str) -> bool:
        """Whether the word is typed back, for what can't be undone. --yes
        skips it."""
        if self.options.yes:
            self.detail(f"{warning} (--yes)")
            return True
        if not interactive():
            raise Stop(
                f"{warning} There's no terminal to ask on: give --yes to go ahead."
            )
        print(warning, file=sys.stderr, flush=True)
        try:
            typed = read_line(f"Type {word} to go ahead: ")
        except Stop:
            return False
        return typed.strip() == word

    def get_captcha(self, page: str) -> str:
        """A captcha solved on Signal's page: the signalcaptcha:// link it
        gives."""
        if not interactive():
            raise Stop(
                f"Signal wants a captcha first: solve it at {page}, and run this "
                f"again with the {CAPTCHA_START} link it gives (see --help)."
            )
        info("Signal wants a captcha solved first:")
        info(f"  1. Open {page}")
        info(
            '  2. Solve it. When "Open Signal" shows, right-click it and copy the link.'
        )
        info(f"     It starts with {CAPTCHA_START} and only works for a minute or so.")
        open_page(page)
        while True:
            captcha = "".join(self.ask("Paste the link:").split())
            if captcha.startswith(CAPTCHA_START) and len(captcha) > len(CAPTCHA_START):
                return captcha
            info(f"That isn't it: the link starts with {CAPTCHA_START}")

    # Requests

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        slow: bool = False,
    ) -> Answer:
        """One request, with the body as JSON, if any: the answer, an error's
        too. Raises Stop if there's none."""
        self.detail(
            f"> {method} {path}" + (f" {shown(body)}" if body is not None else "")
        )
        data = None if body is None else json.dumps(body).encode()
        try:
            request = urllib.request.Request(self.url + path, data=data, method=method)
        except ValueError as e:  # not a URL urllib takes
            raise Stop(f"signal-cli-rest-api can't be at {self.url}: {e}") from e
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with OPENER.open(
                request, timeout=SLOW_TIMEOUT if slow else TIMEOUT
            ) as response:
                answer = Answer(response.status, response.read())
        except urllib.error.HTTPError as e:
            with e:
                body_read = b""
                with contextlib.suppress(OSError, http.client.HTTPException):
                    body_read = e.read()
            answer = Answer(e.code, body_read)
        except (OSError, http.client.HTTPException) as e:  # URLError is an OSError
            why = why_not(e)
            if couldnt_connect(e):
                why += ". Is it running, and there? --url says where"
            elif method != "GET":
                why += ". It may have gone through all the same: see status"
            raise Stop(
                f"No answer from signal-cli-rest-api at {self.url}: {why}"
            ) from e
        self.detail(f"< HTTP {answer.status}")
        return answer

    def change(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        slow: bool = False,
    ) -> Answer:
        """A request that changes something: with --dry-run, only shown, and
        the tool stops."""
        if self.options.dry_run:
            info(f"Would send: {method} {self.url}{path}")
            if body is not None:
                info(f"With: {shown(body)}")
            info("Dry run: nothing has been sent.")
            raise SystemExit(0)
        return self.request(method, path, body, slow=slow)

    def get(self, path: str, what: str, *, slow: bool = False) -> Answer:
        """A GET that must go well; what says what failed, if it doesn't."""
        answer = self.request("GET", path, slow=slow)
        if not answer.ok:
            self.fail(what, answer)
        return answer

    def fail(self, what: str, answer: Answer) -> NoReturn:
        raise Stop(f"{what}: {answer.error()} (HTTP {answer.status})")

    def print_json(self, found: Any) -> None:
        if found is not None:
            info(as_json(found))

    # The account

    def read_about(self) -> None:
        answer = self.get(
            "/v1/about", f"signal-cli-rest-api at {self.url} didn't say what it is"
        )
        self.about = answer.object()

    @property
    def api_version(self) -> str:
        return str(self.about.get("version") or "?")

    @property
    def api_mode(self) -> str:
        return str(self.about.get("mode") or "?")

    def list_accounts(self) -> Answer:
        """The accounts in signal-cli: since its numberless support,
        signal-cli-rest-api lists them as {"number": ..., "aci": ...}, and
        before, by number alone."""
        answer = self.get("/v1/accounts", "Can't list the accounts")
        pairs: list[tuple[str, str]] = []
        for each in answer.list():
            if isinstance(each, str):
                pairs.append(("", each) if is_signal_id(each) else (each, ""))
            elif isinstance(each, dict):
                entry = as_object(each)
                number, aci = entry.get("number"), entry.get("aci")
                pairs.append(
                    (
                        number if isinstance(number, str) else "",
                        aci if isinstance(aci, str) else "",
                    )
                )
        self.pairs = [(number, aci) for number, aci in pairs if number or aci]
        self.accounts = [number or aci for number, aci in self.pairs]
        return answer

    def is_registered(self, who: str) -> bool:
        """Whether signal-cli has the account, by its number or Signal ID,
        which it then keeps."""
        self.list_accounts()
        for number, aci in self.pairs:
            if who and who in (number, aci):
                self.number, self.account_id = number, aci
                return True
        return False

    @property
    def numberless(self) -> bool:
        return not self.number

    def configured_account(self) -> None:
        self.account = self.account or self.settings.value("account")

    def use_account(
        self,
        *,
        registered: bool = True,
        number_only: bool = False,
        id_only: bool = False,
    ) -> None:
        """Settle the account: --account, NEJOMIBOT_ACCOUNT, the bot's
        config, or else the only one signal-cli has. It must be registered in
        signal-cli unless not registered, a phone number if number_only, as
        for registering, and a Signal ID if id_only, as for restoring;
        otherwise either will do."""
        self.configured_account()
        if not self.account:
            self.list_accounts()
            if not self.accounts:
                raise Stop(
                    "signal-cli has no account yet: run setup, or register, restore "
                    "or link."
                )
            if len(self.accounts) > 1:
                raise Stop(
                    f"signal-cli has {len(self.accounts)} accounts, so choose one with "
                    f"--account: {' '.join(self.accounts)}"
                )
            self.account = self.accounts[0]
            self.detail(f"Using the only account, {self.account}")
        self.account = normal_account(self.account)
        if number_only:
            if not is_number(self.account):
                raise Stop(
                    f"Not a phone number in international format: {self.account} "
                    "(like +46701234567)"
                )
        elif id_only:
            if not is_signal_id(self.account):
                raise Stop(
                    f"Not a Signal ID: {self.account}. A Recovery key restores an "
                    "account by its Signal ID, the Account ID that Signal shows."
                )
        elif not (is_number(self.account) or is_signal_id(self.account)):
            raise Stop(
                "Neither a phone number in international format (like +46701234567) "
                f"nor a Signal ID: {self.account}"
            )
        self.account_path = path_part(self.account)
        if registered and not self.is_registered(self.account):
            has = f", which has {' '.join(self.accounts)}" if self.accounts else ""
            raise Stop(
                f"{self.account} isn't registered in signal-cli at {self.url}{has}: "
                "run setup, or register, restore or link."
            )

    def read_me(self) -> None:
        """The account's own entry, with its profile and username."""
        me = f"/v1/contacts/{self.account_path}/{self.account_path}?all_recipients=true"
        self.me = self.get(me, "Can't read the profile").object()

    def mine(self, *keys: str) -> Any:
        """Something of the account's own entry, as profile, given_name."""
        found: Any = self.me
        for key in keys:
            found = as_object(found).get(key)
        return found

    def my_text(self, *keys: str) -> str:
        return text(self.mine(*keys))

    @property
    def has_avatar(self) -> bool:
        return self.mine("profile", "has_avatar") is True

    def show_profile(self) -> None:
        given = self.my_text("profile", "given_name")
        family = self.my_text("profile", "lastname")
        about = self.my_text("profile", "about")
        username = self.my_text("username")
        name = given + (f" {family}" if family else "")
        if self.numberless:
            row("Name", name or "none")
        else:
            row("Name", name or "none, so Signal shows the number")
        if family:
            row("", f"(given name {given}, family name {family})")
        row("About", about or "none")
        row("Avatar", "yes" if self.has_avatar else "none")
        row("Username", f"@{username}" if username else "none")

    # The bot's profile file

    def bot_txt(self) -> KeptLines[tuple[str, str]] | None:
        """bot.txt in the bot's data folder, if it's here: the bot keeps its
        profile there, and at each start changes what differs from it."""
        folder = Path(self.settings.value("data_dir") or DEFAULT_DATA)
        if not (folder.is_dir() and os.access(folder, os.W_OK)):
            return None
        from .profile import kept_in

        return kept_in(folder)

    def keep(self, part: str, value: str) -> None:
        """The part in bot.txt, if it's here, as the bot keeps it."""
        if (lines := self.bot_txt()) is None:
            return
        from .profile import keep

        keep(part, value, lines)
        self.detail(f"In {lines.path()}: {part} {value}".rstrip())

    def keep_avatar(self, avatar: AvatarImage | None) -> None:
        """The avatar sent, beside bot.txt and named there, or none."""
        if (lines := self.bot_txt()) is None:
            return
        from .profile import keep_avatar

        keep_avatar(avatar, lines)
        self.detail(f"In {lines.path()}: the avatar")

    # Changing the profile

    def avatar_of(self, given: str) -> AvatarImage:
        """The avatar to upload, from the picture, made as the bot's /avatar
        makes one."""
        data = picture(given)
        from .profile import make_avatar  # here alone: it takes a while

        try:
            avatar = make_avatar(data, heif=True)
        except Exception as e:  # Pillow's, of many kinds, for what it can't read
            shown_as = "The picture on standard input" if given == "-" else given
            raise Stop(f"{shown_as} isn't a picture the bot can read: {e}") from e
        self.detail(f"Avatar: {avatar.side}x{avatar.side} {avatar.format}")
        if len(avatar.data) > AVATAR_MAX_BYTES:
            raise Stop(
                f"The avatar is {len(avatar.data) // 1024 // 1024} MB, and Signal's "
                "Android app doesn't fetch one over 10 MB."
            )
        return avatar

    def set_profile(
        self, name: str, about: str | None, avatar: str, picture_given: str = ""
    ) -> None:
        """Change the profile: the name, the current one if none is given;
        About, unless None; and the avatar: keep, remove, or new, from the
        picture. signal-cli-rest-api sets the profile as a whole, the given
        name always, and removes the avatar unless one comes along, so the
        current one is sent back, unless it changes. Needs read_me first."""
        given = self.my_text("profile", "given_name")
        family = self.my_text("profile", "lastname")
        if name:
            check_name(name)
            if family:
                warn(
                    f'The profile\'s family name is "{family}", which '
                    f"signal-cli-rest-api can't change, so the name will show as "
                    f'"{name} {family}".'
                )
                if not self.confirm("Go ahead?"):
                    raise Stop("Nothing has been changed.")
        else:
            name = given
            if not name:
                raise Stop(
                    "The profile has no name, and signal-cli-rest-api needs one: give "
                    "--name."
                )
        if about is not None:
            check_about(about)
        new: AvatarImage | None = None
        encoded = ""
        if avatar == "new":
            new = self.avatar_of(picture_given)
            encoded = base64.b64encode(new.data).decode()
        elif avatar == "keep" and self.has_avatar:
            path = f"/v1/contacts/{self.account_path}/{self.account_path}/avatar"
            answer = self.request("GET", path)
            if answer.ok and answer.body:
                self.detail("Sending the current avatar along, so it stays")
                encoded = base64.b64encode(answer.body).decode()
            else:
                warn(
                    "signal-cli can't give back the current avatar, and "
                    "signal-cli-rest-api removes it unless it's sent along."
                )
                if not self.confirm(
                    "Change the profile all the same, and lose the avatar?"
                ):
                    raise Stop("Nothing has been changed.")
        body: dict[str, Any] = {"name": name}
        if about is not None:
            body["about"] = about
        if encoded:
            body["base64_avatar"] = encoded
        answer = self.change(
            "PUT", f"/v1/profiles/{self.account_path}", body, slow=True
        )
        if not answer.ok:
            self.fail("Signal didn't take the profile", answer)
        info("Profile changed.")
        self.keep("name", name)
        if about is not None:
            self.keep("about", about)
        if avatar == "new":
            self.keep_avatar(new)
        elif avatar == "remove":
            self.keep_avatar(None)

    def set_username(self, given: str) -> None:
        """As Signal takes it: it adds a number unless the name has one."""
        wanted = given.removeprefix("@")
        if not re.fullmatch(USERNAME, wanted, re.ASCII):
            raise Stop(
                f"{wanted} can't be a Signal username: 3 to 32 letters, digits or _, "
                "not starting with a digit, maybe with a dot and 2 to 9 digits after "
                "it (name.42)."
            )
        path = f"/v1/accounts/{self.account_path}/username"
        answer = self.change("POST", path, {"username": wanted}, slow=True)
        if not answer.ok:
            # signal-cli-rest-api loses signal-cli's reason
            if "invalid signal-cli response" in answer.error():
                raise Stop(
                    f"Signal turned down {wanted}, and signal-cli-rest-api doesn't say "
                    "why: most likely it's taken, or not allowed. Try another, or "
                    "another number after the dot."
                )
            self.fail(f"Signal didn't take the username {wanted}", answer)
        found = answer.object()
        username = found.get("username")
        # Not "": bot.txt would then have the bot remove it
        username = username if isinstance(username, str) and username else wanted
        self.keep("username", username)
        if self.options.json:
            self.print_json(found)
            return
        row("Username", f"@{username}")
        if isinstance(link := found.get("username_link"), str) and link:
            row("Link", f"{link} (it starts a chat)")

    def set_pin(self) -> None:
        pin = self.ask_secret("New PIN (at least 4 digits or letters):")
        if len(pin) < 4:
            raise Stop("A Signal PIN has at least 4 digits or letters.")
        if self.ask_secret("The same PIN again:") != pin:
            raise Stop("The two PINs differ, so nothing has been changed.")
        path = f"/v1/accounts/{self.account_path}/pin"
        answer = self.change("POST", path, {"pin": utf8(pin, "The PIN")}, slow=True)
        if not answer.ok:
            self.fail("Signal didn't take the PIN", answer)
        info(
            f"PIN set. Signal asks for it when {self.account} is registered anew: keep "
            "it safe."
        )

    def set_privacy(self, seen: bool | None, findable: bool | None) -> None:
        """Each True, False, or None to leave it."""
        if seen is True and findable is False:
            warn(
                "Signal's apps don't allow that: whoever sees the number can find "
                "the account by it."
            )
            if not self.confirm("Set it all the same?"):
                raise Stop("Nothing has been changed.")
        body: dict[str, Any] = {}
        if seen is not None:
            body["share_number"] = seen
        if findable is not None:
            body["discoverable_by_number"] = findable
        path = f"/v1/accounts/{self.account_path}/settings"
        answer = self.change("PUT", path, body, slow=True)
        if not answer.ok:
            self.fail("Signal didn't take the settings", answer)
        if seen is not None:
            row("Number", f"seen by {'everyone' if seen else 'nobody'}")
        if findable is not None:
            row("Findable", f"by number: {'everyone' if findable else 'nobody'}")

    # Registering and linking

    def number_to_register(self) -> None:
        """Settle the number to register: --account, the bot's settings, or
        asked for."""
        self.configured_account()
        if not self.account:
            self.account = "".join(
                self.ask("The phone number to register, like +46701234567:").split()
            )
        self.use_account(registered=False, number_only=True)
        if self.is_registered(self.account):
            warn(
                f"{self.account} is registered in signal-cli already: registering it "
                "again starts afresh, with a new code."
            )
            if not self.confirm("Register it again?"):
                raise Stop("Nothing has been changed.")

    def register(self, voice: bool, captcha: str) -> None:
        """Have Signal send a verification code, by SMS or by a call, going
        through what it may want first: a captcha, or a minute's wait before
        it calls."""
        while True:
            body: dict[str, Any] = {"use_voice": voice}
            if captcha:
                body["captcha"] = captcha
            answer = self.change(
                "POST", f"/v1/register/{self.account_path}", body, slow=True
            )
            if answer.ok:
                break
            why = answer.error()
            if "Captcha required" in why or "Invalid captcha" in why:
                if "Invalid captcha" in why:
                    say(
                        "That captcha didn't work: they're only good for a minute or "
                        "so."
                    )
                captcha = self.get_captcha(REGISTRATION_CAPTCHA)
            elif "Couldn't use SMS verification" in why and not voice:
                say(
                    f"Signal can't send {self.account} an SMS, but it can call with "
                    "the code."
                )
                if not self.confirm("Wait the minute Signal wants, and have it call?"):
                    raise Stop("No code has been sent.")
                countdown(SMS_WAIT)
                voice = True
            else:
                self.fail("Signal didn't send a code", answer)
        if voice:
            info(f"Signal is calling {self.account} with the code.")
        else:
            info(f"Signal is sending {self.account} the code by SMS.")

    def verify(self, code: str, ask_pin: bool) -> None:
        """Finish registering with the code Signal sent, and the registration
        lock PIN if the number has one: asked for first if ask_pin, or once
        Signal wants it."""
        digits = six_digits(code, "A Signal code")
        pin = self.ask_secret("The registration lock PIN:") if ask_pin else ""
        while True:
            body = {"pin": utf8(pin, "The PIN")} if pin else {}
            path = f"/v1/register/{self.account_path}/verify/{digits}"
            answer = self.change("POST", path, body, slow=True)
            if answer.ok:
                break
            why = answer.error()
            if "locked with a pin" in why or "Invalid pin" in why:
                info(why.splitlines()[0])
                if not interactive():
                    raise Stop(
                        "Signal wants the registration lock PIN: run verify again, "
                        "with --pin."
                    )
                pin = self.ask_secret("The registration lock PIN:")
            else:
                self.fail("Signal didn't take the code", answer)
        info(f"{self.account} is registered.")

    def get_code(self) -> str:
        """The code Signal sent, typed in. Enter, when none came, has Signal
        send it again, or call with it, as its apps offer: its first SMS
        doesn't always come (on 2026-10-23 the one sent right after a captcha
        never did, twice, while the next one came at once)."""
        while not (code := self.ask("The code Signal sent (Enter if none came):")):
            how = self.ask(
                "Have Signal send it again by SMS (s), or call with it (c)?", "s"
            )
            try:
                self.register(how.lower().startswith("c"), "")
            except Stop as e:
                error(str(e))
        return code

    def id_to_restore(self) -> bool:
        """Settle the account to restore, by its Signal ID: --account, the
        bot's settings, or asked for; once restoring it here is confirmed.
        Whether signal-cli has it already, so that it's registered anew."""
        self.configured_account()
        if not self.account:
            self.account = self.ask("The account's Signal ID (its Account ID):")
        self.use_account(registered=False, id_only=True)
        again = self.is_registered(self.account)
        if again:
            warn(
                f"{self.account} is registered in signal-cli already: restoring it "
                "again registers it anew."
            )
        say(
            f"Restored, signal-cli is the primary device of {self.account}: "
            "wherever that was before, a phone or another signal-cli, it stops "
            "working. Two copies of an account must never run at once."
        )
        if not self.confirm("Restore it here?"):
            raise Stop("Nothing has been changed.")
        return again

    def recovery_key(self, key_file: str) -> str:
        """The Recovery key, from the file, else typed in unseen: never from
        the command line, the config or the environment, which process
        lists, podman inspect and logs show."""
        if not key_file:
            return stored_key(self.ask_secret("The Recovery key (not shown):"))
        try:
            with Path(key_file).expanduser().open(errors="replace") as f:
                given = f.read(1024)
        except OSError as e:
            raise Stop(
                f"Can't read the Recovery key from {key_file}: {e.strerror or e}"
            ) from e
        return stored_key(given)

    def restore(self, key: str, totp: str, again: bool) -> None:
        """Restore the account with its Recovery key, which needs no code
        from Signal, only a TOTP code if Signal wants one; again if signal-cli
        has the account already."""
        while True:
            body: dict[str, Any] = {"recovery_key": key}
            if totp:
                body["totp"] = totp
            if again:
                body["reregister"] = True
            answer = self.change(
                "POST", f"/v1/register/{self.account_path}", body, slow=True
            )
            if answer.ok:
                break
            if "TOTP token is required" not in answer.error():
                self.fail("Signal didn't restore the account", answer)
            if not interactive():
                raise Stop(
                    "Signal wants a TOTP code too: run restore again, with --totp CODE."
                )
            totp = six_digits(self.ask("The TOTP code Signal wants:"), "A TOTP code")
        info(f"{self.account} is restored.")

    def link_device(self, name: str) -> None:
        """Make signal-cli a linked device of a phone, called name there: show
        the QR code to scan, then wait for the new account to show up."""
        info(
            "Once linked, the bot uses the phone's account. Keep in mind (--help, "
            "LINKED):"
        )
        info(
            "  - What is typed on the phone in a direct chat reaches the bot as if the"
        )
        info(
            "    other person sent it, and a command there acts as theirs: a phone kept"
        )
        info("    for the bot suits it best.")
        info("  - The phone has to come online at least once every 30 days, or Signal")
        info("    unlinks the bot, and only the phone can link it again.")
        self.list_accounts()
        before = set(self.accounts)
        path = f"/v1/qrcodelink/raw?{urlencode({'device_name': name}, quote_via=quote)}"
        answer = self.change("GET", path)
        if not answer.ok:
            self.fail("Can't start linking", answer)
        link = answer.object().get("device_link_uri")
        if not isinstance(link, str) or not link:
            raise Stop("signal-cli-rest-api gave no link for the QR code.")
        info(qr_code(link))
        info("On the phone: Signal > Settings > Linked devices > Link a new device,")
        info(
            f"and scan this code. Waiting for it, {LINK_WAIT // 60} minutes at most..."
        )
        deadline = time.monotonic() + LINK_WAIT
        new = ""
        while not new and time.monotonic() < deadline:
            time.sleep(LINK_POLL)
            self.list_accounts()
            new = next((each for each in self.accounts if each not in before), "")
        if not new:
            raise Stop(
                f"Not linked within {LINK_WAIT // 60} minutes: run link again, for a "
                "new code."
            )
        self.account = new
        self.account_path = path_part(new)
        info(f'Linked: signal-cli has {new} now, as the device "{name}".')
        configured = self.settings.file_value("account")
        if configured and configured != new:
            warn(f'The bot\'s config has account = "{configured}": make it "{new}".')

    # The commands

    def cmd_status(self, args: argparse.Namespace) -> None:
        self.read_about()
        self.use_account()
        self.read_me()
        devices = self.get(
            f"/v1/devices/{self.account_path}", "Can't list the devices"
        ).list()
        identities = self.get(
            f"/v1/identities/{self.account_path}", "Can't list the safety numbers"
        ).list()
        if self.options.json:
            self.print_json(
                {
                    "about": self.about,
                    "account": self.account,
                    "accounts": self.accounts,
                    "me": self.me,
                    "devices": devices,
                    "identities": identities,
                }
            )
            return
        info(
            f"signal-cli-rest-api {self.api_version}, {self.api_mode} mode, at "
            f"{self.url}"
        )
        info()
        count = len(self.accounts)
        if self.numberless:
            row(
                "Account",
                f"{self.account}, without a phone number (signal-cli has {count})",
            )
        else:
            row("Account", f"{self.account} (signal-cli has {count})")
            if self.account_id:
                row("Signal ID", self.account_id)
        self.show_profile()
        if self.numberless and not self.my_text("username"):
            warn(
                "No username: without a phone number, nobody can find the account. "
                "Set one with: username NAME"
            )
        info()
        show_devices(devices)
        info()
        statuses = [each.get("status") for each in objects(identities)]
        info(
            f"Safety numbers: {len(identities)}, {statuses.count('TRUSTED_VERIFIED')} "
            f"verified, {statuses.count('UNTRUSTED')} untrusted"
        )

    def cmd_setup(self, args: argparse.Namespace) -> None:
        if self.options.dry_run:
            raise Stop(
                "setup asks as it goes, so it can't make a dry run: give --dry-run to "
                "the commands it uses."
            )
        if not interactive():
            raise Stop("setup asks questions, so it needs a terminal.")
        self.read_about()
        info(
            f"signal-cli-rest-api {self.api_version}, {self.api_mode} mode, at "
            f"{self.url}"
        )
        if not self.api_mode.startswith("json-rpc"):
            warn("The bot needs json-rpc mode: MODE=json-rpc on the container.")

        step("The account")
        linked = False  # to a phone, just now
        self.configured_account()
        account = normal_account(self.account)
        if (is_number(account) or is_signal_id(account)) and self.is_registered(
            account
        ):
            self.account = account
            info(f"{account} is registered in signal-cli already.")
        else:
            by_id = is_signal_id(account)
            if by_id:
                say(
                    f"The bot's account is {account}, a Signal ID, which takes no "
                    "code: restore the account here with its Recovery key, or link "
                    "to a phone with Signal that has it."
                )
                how = self.ask(
                    "Restore it with its Recovery key (k), or link to a phone with "
                    "Signal (l)?",
                    "k",
                ).lower()
            else:
                say(
                    "The bot needs a Signal account: a number registered here for the "
                    "bot alone, or the account of a phone with Signal, which it is "
                    "linked to."
                )
                how = self.ask(
                    "Register a number as a new Signal account (r), or link to a "
                    "phone with Signal (l)?",
                    "r",
                ).lower()
            if how.startswith("k") and by_id:
                again = self.id_to_restore()
                self.restore(self.recovery_key(""), "", again)
            elif how.startswith("r") and not by_id:
                self.number_to_register()
                self.register(False, "")
                self.verify(self.get_code(), False)
            elif how.startswith("l"):
                self.link_device(DEFAULT_DEVICE)
                linked = True
            else:
                raise Stop(f"Neither {'k' if by_id else 'r'} nor l: stopped.")
        self.use_account()
        self.read_me()

        step("The profile")
        self.show_profile()
        name = self.ask("Name (Enter keeps it):")
        about: str | None = None
        given_about = self.ask("About (Enter keeps it, - removes it):")
        if given_about == "-":
            about = ""
        elif given_about:
            about = given_about
        avatar, picture_given = "keep", ""
        given_avatar = self.ask(
            "Avatar, a picture file (Enter keeps it, - removes it):"
        )
        if given_avatar == "-":
            avatar = "remove"
        elif given_avatar:
            avatar, picture_given = "new", given_avatar
        if name or about is not None or avatar != "keep":
            try:
                self.set_profile(name, about, avatar, picture_given)
                self.read_me()
            except Stop as e:
                error(str(e))
                warn("The profile stays as it was; change it later with: profile")
        if not self.my_text("profile", "given_name"):
            if self.numberless:
                warn("The profile has no name.")
            else:
                warn("The profile has no name, so Signal shows the number.")

        step("The username")
        if self.numberless:
            say(
                "Without a phone number, a username is the only way anyone can find "
                "the account."
            )
        else:
            say("With a username, people can start a chat without the number.")
        while wanted := self.ask("Username (Enter skips it):"):
            try:
                self.set_username(wanted)
                break
            except Stop as e:
                error(str(e))

        step("The PIN")
        if linked:
            say(
                "Only the phone sets the registration lock PIN, in Signal's settings: "
                "a linked device can't. Skipped."
            )
        elif self.numberless:
            say(
                "A registration lock PIN guards a phone number, which this account "
                "doesn't have: its Recovery key restores it. Skipped."
            )
        else:
            say(
                "A registration lock PIN stops anyone else registering the number, "
                "even with its SMS code. Only for a number registered here, not linked."
            )
            if self.confirm("Set a PIN?"):
                try:
                    self.set_pin()
                except Stop as e:
                    error(str(e))
                    warn("No PIN set; set it later with: pin")

        step("Privacy")
        if self.numberless:
            say(
                "Who sees the phone number, and who finds the account by it: this "
                "account has no number. Skipped."
            )
        else:
            seen = self.privacy_answer(
                "Who sees the phone number: everyone or nobody? (Enter leaves it)"
            )
            findable = self.privacy_answer(
                "Who can find the account by its number: everyone or nobody? (Enter "
                "leaves it)"
            )
            if seen is not None or findable is not None:
                try:
                    self.set_privacy(seen, findable)
                except Stop as e:
                    error(str(e))
                    warn("Privacy unchanged; set it later with: privacy")

        step("Done")
        self.cmd_status(args)
        if self.settings.file_value("account") != self.account:
            info()
            info(f'The bot uses it with account = "{self.account}" in its config.')

    def privacy_answer(self, question: str) -> bool | None:
        answer = self.ask(question)
        found = everyone_or_nobody(answer)
        if answer and found is None:
            info("Neither everyone nor nobody, so that stays.")
        return found

    def cmd_register(self, args: argparse.Namespace) -> None:
        self.number_to_register()
        self.register(args.voice, args.captcha or "")
        if interactive():
            self.verify(self.get_code(), False)
            info(f"Next, its name: {PROG} profile --name NAME")
        else:
            info(f"Then: {PROG} verify CODE")

    def cmd_verify(self, args: argparse.Namespace) -> None:
        self.configured_account()
        if not self.account:
            raise Stop("Which number? Give it with --account.")
        self.use_account(registered=False, number_only=True)
        self.verify(args.code, args.pin)
        info(f"Next, its name: {PROG} profile --name NAME")

    def cmd_restore(self, args: argparse.Namespace) -> None:
        totp = six_digits(args.totp, "A TOTP code") if args.totp else ""
        again = self.id_to_restore()
        self.restore(self.recovery_key(args.key_file or ""), totp, again)

    def cmd_link(self, args: argparse.Namespace) -> None:
        self.link_device(args.name or DEFAULT_DEVICE)

    def cmd_profile(self, args: argparse.Namespace) -> None:
        if args.name is not None and not args.name:
            raise Wrong("--name needs the name")
        about = "" if args.no_about else args.about
        avatar = (
            "remove" if args.no_avatar else "new" if args.avatar is not None else "keep"
        )
        changes = bool(args.name) or about is not None or avatar != "keep"
        self.use_account()
        self.read_me()
        if changes:
            self.set_profile(args.name or "", about, avatar, args.avatar or "")
            self.read_me()
        if self.options.json:
            self.print_json(self.me)
            return
        self.show_profile()
        if not changes:
            info("(signal-cli-rest-api doesn't show the emoji before About)")

    def cmd_username(self, args: argparse.Namespace) -> None:
        if args.remove and args.name:
            raise Wrong("Give a username, or --remove, not both")
        self.use_account()
        if args.name:
            self.set_username(args.name)
            return
        self.read_me()
        username = self.my_text("username")
        if not args.remove:
            if self.options.json:
                self.print_json({"username": self.mine("username")})
            elif username:
                row("Username", f"@{username}")
            else:
                info("No username.")
            return
        if not username:
            raise Stop("There's no username to remove.")
        if not self.confirm(
            f"Remove the username @{username}? Its link stops working, and anyone may "
            "take it."
        ):
            raise Stop("Nothing has been changed.")
        answer = self.change(
            "DELETE", f"/v1/accounts/{self.account_path}/username", slow=True
        )
        if not answer.ok:
            self.fail("Signal didn't remove the username", answer)
        self.keep("username", "")
        info("Username removed.")

    def cmd_pin(self, args: argparse.Namespace) -> None:
        if args.given:
            raise Wrong(
                "pin takes no PIN: it's asked for, to stay out of the shell history"
            )
        self.use_account()
        if not args.remove:
            if self.numberless:
                warn(
                    f"A registration lock PIN guards a phone number, which "
                    f"{self.account} doesn't have: its Recovery key restores it."
                )
                if not self.confirm("Set a PIN all the same?"):
                    raise Stop("Nothing has been changed.")
            self.set_pin()
            return
        if not self.confirm(
            "Remove the registration lock PIN? Then anyone who gets an SMS code for "
            f"{self.account} can register it."
        ):
            raise Stop("Nothing has been changed.")
        answer = self.change(
            "DELETE", f"/v1/accounts/{self.account_path}/pin", slow=True
        )
        if not answer.ok:
            self.fail("Signal didn't remove the PIN", answer)
        info("PIN removed.")

    def cmd_privacy(self, args: argparse.Namespace) -> None:
        seen = findable = None
        if args.number_seen_by is not None:
            seen = everyone_or_nobody(args.number_seen_by)
            if seen is None:
                raise Wrong("--number-seen-by is everyone or nobody")
        if args.findable_by_number is not None:
            findable = everyone_or_nobody(args.findable_by_number)
            if findable is None:
                raise Wrong("--findable-by-number is everyone or nobody")
        if seen is None and findable is None:
            info("Who sees the phone number, and who can find the account by it:")
            info(
                f"  {PROG} privacy --number-seen-by everyone|nobody "
                "--findable-by-number everyone|nobody"
            )
            info("signal-cli-rest-api can't show how they're set now.")
            return
        self.use_account()
        if self.numberless:
            raise Stop(
                f"These settings are about the phone number, and {self.account} has "
                "none."
            )
        self.set_privacy(seen, findable)

    def cmd_rate_limit(self, args: argparse.Namespace) -> None:
        token, captcha, to = args.token or "", args.captcha or "", args.to or ""
        if not token and not to:
            raise Wrong("rate-limit needs the challenge TOKEN, or --to WHO to get one")
        if token and to:
            raise Wrong("rate-limit takes the challenge TOKEN or --to WHO, not both")
        self.use_account()
        if to:
            token = self.challenge_from(to)
        if not captcha:
            captcha = self.get_captcha(CHALLENGE_CAPTCHA)
        path = f"/v1/accounts/{self.account_path}/rate-limit-challenge"
        body = {"challenge_token": token, "captcha": captcha}
        answer = self.change("POST", path, body, slow=True)
        if not answer.ok:
            self.fail("Signal didn't lift the rate limit", answer)
        info("Rate limit lifted: the bot can send again.")

    def challenge_from(self, who: str) -> str:
        """Send who a short message, for the challenge Signal gives with a
        rate limit. Stops if Signal takes the message, as then the account
        isn't rate-limited."""
        body = {
            "number": self.account,
            "recipients": [who],
            "message": "A test from the bot's admin, to see whether Signal lets the "
            "bot send. It can be ignored.",
        }
        answer = self.change("POST", "/v2/send", body, slow=True)
        if answer.ok:
            info(
                f"Signal took the message to {who}, so the account isn't rate-limited."
            )
            raise SystemExit(0)
        if answer.status != 429:
            self.fail(f"Couldn't send to {who}", answer)
        tokens = answer.object().get("challenge_tokens")
        token = (
            cast("list[Any]", tokens)[0]
            if isinstance(tokens, list) and tokens
            else None
        )
        if not isinstance(token, str) or not token:
            raise Stop(
                "Signal rate-limits the account, but offers no captcha for it: wait "
                "for the limit to lift."
            )
        info("Signal rate-limits the account, and lifts it for a solved captcha.")
        return token

    def cmd_unregister(self, args: argparse.Namespace) -> None:
        self.use_account()
        say(
            f"Unregistering {self.account}: Signal stops delivering its messages to "
            "signal-cli, and the bot stops working until it's registered or linked "
            "again."
        )
        if args.delete_account:
            warn(
                "--delete-account deletes the Signal account itself, for good: its "
                "profile, username and groups go, and the number has to start afresh."
            )
        elif self.numberless:
            warn(
                f"Without a phone number, only its Recovery key restores "
                f"{self.account}, and signal-cli-rest-api can't use one yet (see the "
                "README)."
            )
        if args.delete_local_data:
            say(
                "--delete-local-data deletes what signal-cli keeps of it too: keys, "
                "contacts and groups."
            )
        if not self.confirm_typed("This can't be undone.", self.account):
            raise Stop("Nothing has been changed.")
        body = {
            "delete_account": args.delete_account,
            "delete_local_data": args.delete_local_data,
        }
        answer = self.change(
            "POST", f"/v1/unregister/{self.account_path}", body, slow=True
        )
        if not answer.ok:
            self.fail("Signal didn't unregister it", answer)
        info(f"{self.account} is unregistered.")

    def cmd_delete_local_data(self, args: argparse.Namespace) -> None:
        self.use_account(registered=False)
        if args.even_if_registered:
            warn(
                f"{self.account} may still be registered: without its keys, signal-cli "
                "can't read what Signal still delivers to it."
            )
        if not self.confirm_typed(
            f"This deletes all signal-cli keeps of {self.account}: keys, contacts and "
            "groups. It can't be undone.",
            self.account,
        ):
            raise Stop("Nothing has been changed.")
        body = {"ignore_registered": args.even_if_registered}
        path = f"/v1/devices/{self.account_path}/local-data"
        answer = self.change("DELETE", path, body, slow=True)
        if not answer.ok:
            self.fail("signal-cli didn't delete it", answer)
        info(f"What signal-cli kept of {self.account} is deleted.")

    def cmd_devices(self, args: argparse.Namespace) -> None:
        what, value = args.what or "list", args.value
        if what in ("list", "sync") and value is not None:
            raise Wrong(f"devices {what} takes no more arguments")
        if what in ("add", "remove") and value is None:
            needs = "the device's link" if what == "add" else "the device ID"
            raise Wrong(f"devices {what} needs {needs}")
        if what == "remove" and not (value or "").isdecimal():
            raise Wrong("A device ID is a number, as devices shows")
        self.use_account()
        path = f"/v1/devices/{self.account_path}"
        if what == "list":
            answer = self.get(path, "Can't list the devices")
            if self.options.json:
                self.print_json(answer.json())
            else:
                show_devices(answer.list())
        elif what == "add":
            link = value or ""
            if not link.startswith(DEVICE_LINK):
                raise Stop(
                    "That isn't a device link: it starts with sgnl://linkdevice?"
                )
            answer = self.change("POST", path, {"uri": link}, slow=True)
            if not answer.ok:
                self.fail("Signal didn't link the device", answer)
            info("Linked: it shows in devices once it has finished setting up.")
        elif what == "remove":
            number = int(value or "0")
            if number == 1:
                raise Stop(
                    "Device 1 is the primary device, which can't be unlinked: "
                    "unregister ends it."
                )
            devices = self.get(path, "Can't list the devices").list()
            found = next(
                (each for each in objects(devices) if each.get("id") == number), None
            )
            if found is None:
                raise Stop(f"There's no device {number}: see devices.")
            name = found.get("name") or "(no name)"
            if not self.confirm(
                f'Unlink device {number}, "{name}"? It stops getting messages, and has '
                "to be linked anew."
            ):
                raise Stop("Nothing has been changed.")
            answer = self.change("DELETE", f"{path}/{number}", slow=True)
            if not answer.ok:
                self.fail("Signal didn't unlink the device", answer)
            info(f"Device {number} unlinked.")
        else:  # sync
            answer = self.change(
                "POST", f"/v1/contacts/{self.account_path}/sync", slow=True
            )
            if not answer.ok:
                self.fail("Signal didn't take the contacts", answer)
            info("Contact list sent to the linked devices.")

    def cmd_identities(self, args: argparse.Namespace) -> None:
        self.use_account()
        answer = self.get(
            f"/v1/identities/{self.account_path}", "Can't list the safety numbers"
        )
        if self.options.json:
            self.print_json(answer.json())
            return
        contacts = self.get(
            f"/v1/contacts/{self.account_path}?all_recipients=true",
            "Can't list the contacts",
        ).list()
        names = {
            uuid: name
            for each in objects(contacts)
            if (uuid := text(each.get("uuid"))) and (name := contact_name(each))
        }

        def shown_as(identity: Object) -> list[str]:
            """Their name, if known, their number, if any, and their ID."""
            uuid = text(identity.get("uuid"))
            parts = [names.get(uuid, ""), text(identity.get("number")), uuid]
            return [part for part in parts if part]

        for identity in sorted(
            objects(answer.list()),
            key=lambda identity: (shown_as(identity) or [""])[0].casefold(),
        ):
            info(", ".join(shown_as(identity)))
            status = text(identity.get("status"))
            info(f"  {STATUSES.get(status, status) or '?'}")
            digits = re.sub(r"[^0-9]", "", text(identity.get("safety_number")))
            groups = [digits[i : i + 5] for i in range(0, len(digits), 5)]
            for start in range(0, len(groups), 4):
                info("  " + " ".join(groups[start : start + 4]))
            info()

    def cmd_trust(self, args: argparse.Namespace) -> None:
        if args.unverified and args.safety_number:
            raise Wrong("--unverified takes nothing more")
        if not args.unverified and not args.safety_number:
            raise Wrong("trust needs WHO and their SAFETY_NUMBER, or --unverified")
        digits = re.sub(r"[^0-9]", "", "".join(args.safety_number))
        if not args.unverified and len(digits) != 60:
            raise Stop(f"A safety number has 60 digits, and that's {len(digits)}.")
        self.use_account()
        who = args.who
        if args.unverified:
            if not self.confirm(
                f"Accept the keys of {who} as they are, without verifying them?"
            ):
                raise Stop("Nothing has been changed.")
            body: dict[str, Any] = {"trust_all_known_keys": True}
        else:
            body = {"verified_safety_number": digits}
        path = f"/v1/identities/{self.account_path}/trust/{path_part(who)}"
        answer = self.change("PUT", path, body)
        if not answer.ok:
            self.fail("signal-cli didn't trust it", answer)
        if args.unverified:
            say(
                f"{who} is trusted, but not verified. To verify, compare their safety "
                "number with the one on their phone, then:"
            )
            info(f"  {PROG} trust {who} SAFETY_NUMBER")
        else:
            info(f"{who} is verified.")

    def cmd_search(self, args: argparse.Namespace) -> None:
        for number in args.numbers:
            if not is_number(number):
                raise Stop(
                    f"Not a phone number in international format: {number} "
                    "(like +46701234567)"
                )
        self.use_account()
        query = urlencode(
            [("numbers", number) for number in args.numbers], quote_via=quote
        )
        answer = self.get(
            f"/v1/search/{self.account_path}?{query}", "Signal didn't say", slow=True
        )
        if self.options.json:
            self.print_json(answer.json())
            return
        for each in objects(answer.list()):
            on = "on Signal" if each.get("registered") is True else "not on Signal"
            info(f"{each.get('number')}  {on}")

    def cmd_accounts(self, args: argparse.Namespace) -> None:
        answer = self.list_accounts()
        if self.options.json:
            self.print_json(answer.json())
        elif self.accounts:
            for account in self.accounts:
                info(account)
        else:
            info("No accounts yet: run setup.")

    def cmd_about(self, args: argparse.Namespace) -> None:
        self.read_about()
        if self.options.json:
            self.print_json(self.about)
            return
        versions = self.about.get("versions")
        listed = (
            ", ".join(map(str, cast("list[Any]", versions)))
            if isinstance(versions, list)
            else ""
        )
        row("Version", f"{self.api_version} (build {self.about.get('build') or '?'})")
        row("Mode", self.api_mode)
        row("API versions", listed)
        row("URL", self.url)

    def cmd_log_level(self, args: argparse.Namespace) -> None:
        if args.level is None:
            answer = self.get("/v1/configuration", "Can't read the configuration")
            if self.options.json:
                self.print_json(answer.json())
            else:
                level = as_object(answer.object().get("logging")).get("Level")
                row("Log level", str(level or "?"))
            return
        body = {"logging": {"Level": args.level}}
        answer = self.change("POST", "/v1/configuration", body)
        if not answer.ok:
            self.fail("The log level stays as it was", answer)
        row("Log level", args.level)

    def cmd_trust_mode(self, args: argparse.Namespace) -> None:
        self.read_about()
        self.use_account()
        path = f"/v1/configuration/{self.account_path}/settings"
        json_rpc = self.api_mode.startswith("json-rpc")
        if args.mode is None:
            answer = self.get(path, "Can't read the trust mode")
            mode = answer.object().get("trust_mode")
            if self.options.json:
                self.print_json(answer.json())
            elif json_rpc:
                say(
                    f"In {self.api_mode} mode, the container's "
                    "JSON_RPC_TRUST_NEW_IDENTITIES sets it: always, on-first-use or "
                    "never (signal-cli's default: on-first-use). signal-cli-rest-api's "
                    f"own setting is {mode}, unused in this mode."
                )
            else:
                row("Trust mode", str(mode))
            return
        if json_rpc:
            raise Stop(
                f"In {self.api_mode} mode it's set on the container: "
                f"JSON_RPC_TRUST_NEW_IDENTITIES={args.mode}, and a restart."
            )
        answer = self.change("POST", path, {"trust_mode": args.mode})
        if not answer.ok:
            self.fail("The trust mode stays as it was", answer)
        row("Trust mode", args.mode)


def day(milliseconds: Any) -> str:
    """The day of a time signal-cli gives in milliseconds, here; ? if none."""
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, int | float):
        return "?"
    if milliseconds <= 0:
        return "?"
    try:
        return datetime.fromtimestamp(milliseconds / 1000).strftime("%Y-%m-%d")
    except OverflowError, OSError, ValueError:
        return "?"


def show_devices(devices: Sequence[Any]) -> None:
    listed = objects(list(devices))

    def number(device: Object) -> int:
        found = device.get("id")
        return found if isinstance(found, int) else 0

    for device in sorted(listed, key=number):
        found = device.get("id")
        kind = "primary" if found == 1 else "linked"
        name = device.get("name") or "(no name)"
        dates = (
            f"added {day(device.get('creation_timestamp'))}, "
            f"seen {day(device.get('last_seen_timestamp'))}"
        )
        info(f"{'#' + str(found):<4} {kind:<8} {name:<20} {dates}")


def contact_name(contact: Object) -> str | None:
    """Someone's name, as signal-cli knows it: their nickname, the name in
    the contacts, their profile's, else their username."""
    profile = as_object(contact.get("profile"))
    parts = [profile.get("given_name"), profile.get("lastname")]
    full = " ".join(part for part in parts if isinstance(part, str) and part)
    candidates = [
        as_object(contact.get("nickname")).get("name"),
        contact.get("name"),
        full,
        contact.get("username"),
    ]
    return next((each for each in candidates if isinstance(each, str) and each), None)


# The command line


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Wrong(message)


class Help(argparse.Action):
    def __init__(self, option_strings: Sequence[str], dest: str, **kwargs: Any) -> None:
        super().__init__(
            option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, nargs=0
        )

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        print(HELP, end="")
        raise SystemExit(0)


# The options with values, which take the next argument as theirs whatever
# it is, - and --name included, as --about -x does
VALUED = {
    "-u": "--url",
    "--url": "--url",
    "-a": "--account",
    "--account": "--account",
    "-c": "--config",
    "--config": "--config",
    **{
        option: option
        for option in (
            "--name",
            "--about",
            "--avatar",
            "--captcha",
            "--key-file",
            "--totp",
            "--number-seen-by",
            "--findable-by-number",
            "--to",
        )
    },
}


def joined(argv: Sequence[str]) -> list[str]:
    """The arguments, each option with a value joined to it, as --about=-x,
    which argparse takes, as it doesn't take --about -x."""
    found: list[str] = []
    rest = list(argv)
    while rest:
        argument = rest.pop(0)
        if argument == "--":
            found += [argument, *rest]
            break
        if argument in VALUED and rest:
            found.append(f"{VALUED[argument]}={rest.pop(0)}")
        else:
            found.append(argument)
    return found


def options_parser(*, defaults: bool) -> Parser:
    """The options, before or after the command: with defaults for the tool's,
    and without for the commands', so that one given before the command
    stays."""

    def default(value: Any) -> Any:
        return value if defaults else argparse.SUPPRESS

    parser = Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("-u", "--url", default=default(None))
    parser.add_argument("-a", "--account", default=default(None))
    parser.add_argument("-c", "--config", type=Path, default=default(None))
    for short, long in (
        ("-y", "--yes"),
        ("-n", "--dry-run"),
        ("-j", "--json"),
        ("-v", "--verbose"),
    ):
        parser.add_argument(short, long, action="store_true", default=default(False))
    parser.add_argument("-h", "--help", action=Help)
    return parser


def arguments(argv: Sequence[str]) -> argparse.Namespace:
    """Raises Wrong."""
    parser = Parser(
        prog=PROG,
        add_help=False,
        allow_abbrev=False,
        parents=[options_parser(defaults=True)],
    )
    commands = parser.add_subparsers(dest="command", parser_class=Parser)
    common = [options_parser(defaults=False)]

    def command(name: str) -> Parser:
        return commands.add_parser(
            name, parents=common, add_help=False, allow_abbrev=False
        )

    for name in ("status", "setup", "identities", "accounts", "about", "help"):
        command(name)
    register = command("register")
    register.add_argument("--voice", action="store_true")
    register.add_argument("--captcha")
    verify = command("verify")
    verify.add_argument("code")
    verify.add_argument("--pin", action="store_true")
    restore = command("restore")
    restore.add_argument("--key-file")
    restore.add_argument("--totp")
    command("link").add_argument("name", nargs="?")
    profile = command("profile")
    profile.add_argument("--name")
    about = profile.add_mutually_exclusive_group()
    about.add_argument("--about")
    about.add_argument("--no-about", action="store_true")
    avatar = profile.add_mutually_exclusive_group()
    avatar.add_argument("--avatar")
    avatar.add_argument("--no-avatar", action="store_true")
    username = command("username")
    username.add_argument("name", nargs="?")
    username.add_argument("--remove", action="store_true")
    pin = command("pin")
    pin.add_argument("given", nargs="?")
    pin.add_argument("--remove", action="store_true")
    privacy = command("privacy")
    privacy.add_argument("--number-seen-by")
    privacy.add_argument("--findable-by-number")
    rate_limit = command("rate-limit")
    rate_limit.add_argument("token", nargs="?")
    rate_limit.add_argument("captcha", nargs="?")
    rate_limit.add_argument("--to")
    unregister = command("unregister")
    unregister.add_argument("--delete-account", action="store_true")
    unregister.add_argument("--delete-local-data", action="store_true")
    command("delete-local-data").add_argument(
        "--even-if-registered", action="store_true"
    )
    devices = command("devices")
    devices.add_argument("what", nargs="?", choices=("list", "add", "remove", "sync"))
    devices.add_argument("value", nargs="?")
    trust = command("trust")
    trust.add_argument("who")
    trust.add_argument("safety_number", nargs="*")
    trust.add_argument("--unverified", action="store_true")
    command("search").add_argument("numbers", nargs="+")
    command("log-level").add_argument(
        "level", nargs="?", choices=("debug", "info", "warn")
    )
    command("trust-mode").add_argument(
        "mode", nargs="?", choices=("always", "on-first-use", "never")
    )
    return parser.parse_args(joined(argv))


COMMANDS: dict[str, Callable[[Tool, argparse.Namespace], None]] = {
    "status": Tool.cmd_status,
    "setup": Tool.cmd_setup,
    "register": Tool.cmd_register,
    "verify": Tool.cmd_verify,
    "restore": Tool.cmd_restore,
    "link": Tool.cmd_link,
    "profile": Tool.cmd_profile,
    "username": Tool.cmd_username,
    "pin": Tool.cmd_pin,
    "privacy": Tool.cmd_privacy,
    "rate-limit": Tool.cmd_rate_limit,
    "unregister": Tool.cmd_unregister,
    "delete-local-data": Tool.cmd_delete_local_data,
    "devices": Tool.cmd_devices,
    "identities": Tool.cmd_identities,
    "trust": Tool.cmd_trust,
    "search": Tool.cmd_search,
    "accounts": Tool.cmd_accounts,
    "about": Tool.cmd_about,
    "log-level": Tool.cmd_log_level,
    "trust-mode": Tool.cmd_trust_mode,
}


def run(argv: Sequence[str]) -> None:
    """Raises Stop and Wrong."""
    args = arguments(argv)
    if args.command == "help":
        print(HELP, end="")
        return
    options = Options(
        url=args.url,
        account=args.account,
        config=args.config,
        yes=args.yes,
        dry_run=args.dry_run,
        json=args.json,
        verbose=args.verbose,
    )
    if interactive():
        with contextlib.suppress(ImportError):
            import readline  # noqa: F401  # pyright: ignore[reportUnusedImport]  # line editing
    COMMANDS[args.command or "status"](Tool(options), args)


def main() -> None:
    # What the bot's code logs, as when bot.txt can't be written
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        run(sys.argv[1:])
    except Stop as e:
        error(str(e))
        sys.exit(1)
    except Wrong as e:
        error(f"{e} (see --help)")
        sys.exit(2)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        sys.exit(130)
