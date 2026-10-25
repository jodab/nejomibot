"""Who may use the bot.

The admins may use every command; the admin commands only in a direct chat
with the bot. They're those in the config, and those the config's admins
make admins with /admin add (admins.py). Everyone else may use the everyday
commands if they're on the allowed list: a contact, in a direct chat with the
bot, or a group, where anyone in it may use them, there.

The allowed list is a file, data_dir/allowed.txt: a phone number, Signal
ID or group ID a line, and after a # who that is. The admins see it with
/allowed and change it with /allow and /disallow (allowed.py). It can be
changed by hand too: the bot rereads it when it changes, and leaves comments
and lines it can't read as they are. Without the file, the bot starts an
empty one; in debug mode, one with just debug_group. The admins added are
kept the same way, in data_dir/admins.txt, by Signal ID only: a phone
number can change hands, a Signal ID can't.

The config's admins are on neither list, so no command can take away what
they may do.

The bot names people by the name signal-cli has for them, else by what a
list has after their #, with their phone number where it's known: Alice
(+46701234567). Someone who doesn't share their number is known to
signal-cli by their Signal ID alone, so a number on the lists can't name
them, nor match their direct messages, which come without it. Such numbers
the bot looks up, once each, at a start and as /allow adds one: Signal says
whose each is, unless its owner keeps it from being found by number, and
signal-cli keeps the two together. Then the bot writes the names it knows
after the # of the lines that have none.
"""

import logging
import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, TypeAdapter
from signalbot import DataMessage, SignalBot

from . import rest
from .account import fetch_recipients
from .config import GROUP_ID, PHONE_NUMBER, SIGNAL_ID, get_settings
from .files import write_privately
from .messages import describe

logger = logging.getLogger(__name__)

# The bot looks for changes to the file at most this often, in seconds, as it
# checks the list for every message
REREAD = 2.0
MAX_ENTRIES = 1000

HEADER = (
    "# Who may use nejomibot's everyday commands, besides its admins: a phone",
    "# number, Signal ID or group ID per line, and after a # who that is.",
    "# Changed with /allow and /disallow in Signal, or by hand: the bot",
    "# rereads it, and leaves comments and other lines as they are.",
)
ADMINS_HEADER = (
    "# nejomibot's admins besides those in its config, who made them admins: a",
    "# Signal ID per line, and after a # who that is. Changed with /admin add",
    "# and /admin remove in Signal, or by hand: the bot rereads it, and leaves",
    "# comments and other lines as they are.",
)


def chat_id_of(text: str) -> str | None:
    """The text as a phone number, Signal ID (in lower case) or group ID, if
    it's one of them."""
    text = text.strip()
    if re.match(SIGNAL_ID, text.lower()):
        return text.lower()
    if re.match(PHONE_NUMBER, text) or re.match(GROUP_ID, text):
        return text
    return None


def is_group(chat_id: str) -> bool:
    return chat_id.startswith("group.")


@dataclass(frozen=True)
class Entry:
    id: str  # a phone number, Signal ID or group ID
    note: str = ""  # who that is, as the file has it after the #

    @property
    def line(self) -> str:
        """As the file has it: the ID, then the note on one line."""
        note = " ".join(self.note.split())
        return f"{self.id}  # {note}" if note else self.id


def parse(line: str) -> Entry | None:
    """The entry on a line of the file; None for a blank line or a comment.
    Raises ValueError if the line is neither."""
    text, _hash, note = line.partition("#")
    if not text.strip():
        return None
    if (chat_id := chat_id_of(text)) is None:
        raise ValueError(f"{text.strip()} isn't a phone number, Signal ID or group ID")
    return Entry(chat_id, note.strip())


def entry_id(line: str) -> str | None:
    """The ID on a line of the file, if it has one."""
    try:
        entry = parse(line)
    except ValueError:
        return None
    return entry.id if entry else None


class AllowedList:
    """A list of chats, as its file has it: the allowed list, or the admins
    added to the config's, by Signal ID only."""

    def __init__(
        self,
        file: Callable[[], Path] = lambda: get_settings().allowed_file,
        header: Sequence[str] = HEADER,
        *,
        signal_ids_only: bool = False,
    ) -> None:
        self.file = file
        self.header = tuple(header)
        self.signal_ids_only = signal_ids_only
        self.reset()

    def reset(self) -> None:
        """As at a start, with nothing read yet."""
        self.lines: list[str] = []  # the file's, all of them
        self.entries: list[Entry] = []  # each chat once, in the file's order
        self.broken: list[str] = []  # lines that can't be read
        self.path: Path | None = None  # the file read
        self.seen: tuple[int, int] | None = None  # its mtime and size, if read
        self.checked = 0.0  # when the file was last looked at, monotonic

    @property
    def ids(self) -> set[str]:
        return {entry.id for entry in self.entries}

    def parse(self, line: str) -> Entry | None:
        """The entry on a line, as parse() reads it, but anything else than a
        Signal ID on a list of those only. Raises ValueError."""
        entry = parse(line)
        if entry and self.signal_ids_only and not re.match(SIGNAL_ID, entry.id):
            raise ValueError(f"{entry.id} isn't a Signal ID")
        return entry

    def take(self, lines: list[str]) -> None:
        """Make the lines the list."""
        entries: dict[str, Entry] = {}
        broken: list[str] = []
        for number, line in enumerate(lines, start=1):
            try:
                entry = self.parse(line)
            except ValueError as e:
                # The line may be someone's number: /allowed shows it
                name = self.file().name
                logger.error("%s line %d left alone, as it can't be read", name, number)
                logger.debug("%s line %d: %s", name, number, e)
                broken.append(line)
                continue
            if entry is not None:
                entries.setdefault(entry.id, entry)
        self.lines, self.entries, self.broken = lines, list(entries.values()), broken

    def read(self) -> None:
        """Read the file, or make it if there's none. If it can't be read, the
        list stays as it was."""
        path = self.path = self.file()
        self.checked = time.monotonic()
        try:
            stat = path.stat()
        except FileNotFoundError:
            self.make()
            return
        except OSError as e:
            logger.error("Could not read %s, the list stays as it was: %r", path, e)
            return
        # Seen, even if it can't be read, so the error is logged once a change
        self.seen = (stat.st_mtime_ns, stat.st_size)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as e:
            logger.error("Could not read %s, the list stays as it was: %r", path, e)
            return
        self.take(lines)

    def make(self) -> None:
        """Start the file: empty, or in debug mode, with just debug_group,
        unless it's for Signal IDs only."""
        settings = get_settings()
        debug = settings.debug and not self.signal_ids_only
        debug_group = settings.debug_group if debug else None
        lines = [*self.header, *([debug_group] if debug_group else [])]
        try:
            self.save(lines)
        except OSError as e:
            logger.error("Could not make %s, so the list is empty: %r", self.path, e)
            self.take(lines)
            self.seen = None  # not tried again until a file turns up
            return
        logger.info("Made %s, with %d on it", self.path, len(self.ids))

    def save(self, lines: list[str]) -> None:
        """Write the lines to the file, and make them the list. Raises OSError,
        and then changes neither."""
        path = self.path = self.file()
        write_privately(path, "\n".join(lines) + "\n")
        stat = path.stat()
        self.take(lines)
        self.seen = (stat.st_mtime_ns, stat.st_size)

    def changed(self) -> bool:
        if self.path is None:  # not read yet
            return True
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return self.seen is not None  # it was there
        except OSError:
            return False  # can't tell: the list stays as it is
        return (stat.st_mtime_ns, stat.st_size) != self.seen

    def reread(self) -> AllowedList:
        """The list, read again if the file has changed."""
        if self.changed():
            self.read()
        self.checked = time.monotonic()
        return self

    def current(self) -> AllowedList:
        """The list, read again if the file has changed since a look at it
        more than REREAD seconds ago."""
        if time.monotonic() - self.checked < REREAD:
            return self
        return self.reread()

    def start(self) -> None:
        """Read the list, or make it, as in debug mode, where it's always new."""
        self.read()

    def add(self, entry: Entry) -> None:
        """Raises OSError if the file can't be written; then nothing changes."""
        self.reread()
        self.save([*self.lines, entry.line])

    def remove(self, chat_id: str) -> list[tuple[int, str]]:
        """Every line with the ID goes; comments and lines that can't be read
        stay. The lines that went, and where they were. Raises OSError if the
        file can't be written; then nothing changes."""
        self.reread()
        lines = list(enumerate(self.lines))
        gone = [(i, line) for i, line in lines if entry_id(line) == chat_id]
        self.save([line for _i, line in lines if entry_id(line) != chat_id])
        return gone

    def restore(self, lines: list[tuple[int, str]]) -> None:
        """Put lines that were removed back where they were, unless their ID
        is back already. Raises OSError; then nothing changes."""
        self.reread()
        now = list(self.lines)
        for index, line in lines:
            if entry_id(line) not in self.ids:
                now.insert(min(index, len(now)), line)
        self.save(now)

    def name(self, names: Mapping[str, str]) -> int:
        """Write who that is after the # of each line with nothing there, by
        the names given; how many got one. Raises OSError; then nothing
        changes."""
        self.reread()
        lines: list[str] = []
        for line in self.lines:
            try:
                entry = self.parse(line)
            except ValueError:
                entry = None
            if entry and not entry.note and (name := names.get(entry.id)):
                line = Entry(entry.id, name).line
            lines.append(line)
        count = sum(new != old for new, old in zip(lines, self.lines, strict=True))
        if count:
            self.save(lines)
        return count


allowed_list = AllowedList()
# The admins the config's admins made admins
admin_list = AllowedList(
    lambda: get_settings().admins_file, ADMINS_HEADER, signal_ids_only=True
)


def sent_by(message: DataMessage, ids: Collection[str]) -> bool:
    """Whether one of these phone numbers or Signal IDs sent the message."""
    return any(
        who in ids for who in (message.source_number, message.source_uuid) if who
    )


def is_admin(message: DataMessage) -> bool:
    """Whether an admin sent the message: one in the config, or one added."""
    return sent_by(message, get_settings().admins) or sent_by(
        message, admin_list.current().ids
    )


def is_config_admin(message: DataMessage) -> bool:
    """Whether one of the config's admins sent the message: only they add and
    remove admins."""
    return sent_by(message, get_settings().admins)


def from_admin(message: object) -> bool:
    """Whether the message is an admin's, as the admin commands take it."""
    return isinstance(message, DataMessage) and is_admin(message)


def admins() -> list[str]:
    """Every admin: the config's, then those added, as their file lists them."""
    added = [entry.id for entry in admin_list.current().entries]
    return list(dict.fromkeys([*get_settings().admins, *added]))


def permits(bot: SignalBot, message: object) -> bool:
    """Whether the message's sender may use the everyday commands where they
    sent it: an admin or a contact on the list in a direct chat, anyone in a
    group on the list."""
    if not isinstance(message, DataMessage):
        return False
    allowed = allowed_list.current().ids
    if message.is_group():
        return bot.groups.get_id(message.source_or_group_id()) in allowed
    return is_admin(message) or sent_by(message, allowed)


def recipients() -> list[str]:
    """Every contact and group the bot is set up to talk to: those in the
    config, on the allowed list, and the admins added."""
    return sorted(
        {
            *get_settings().configured_recipients,
            *allowed_list.current().ids,
            *admin_list.current().ids,
        }
    )


class Names(dict[str, str]):
    """Names by phone number, Signal ID and group ID: of the groups the bot is
    in, of the people signal-cli knows by name, else as the lists have them
    after their #; and the phone numbers and Signal usernames signal-cli
    knows people by, by their Signal ID."""

    def __init__(self) -> None:
        super().__init__()
        self.numbers: dict[str, str] = {}
        self.usernames: dict[str, str] = {}

    def of(self, who: str, name: str = "") -> str:
        """Who that is, as the bot shows them: a group by its name; a person
        by their name, else by the name given, with their phone number where
        it's known, as 'Alice (+46701234567)', else their username, as
        'Alice (@alice.42)'; by those alone, else by the start of their
        Signal ID."""
        if is_group(who):
            return self.get(who, who)
        number = who if re.match(PHONE_NUMBER, who) else self.numbers.get(who)
        username = self.usernames.get(who)
        name = self.get(who) or (self.get(number) if number else None) or name
        if username and name == username:  # their username is all the name
            name = f"@{username}"
        handle = number or (f"@{username}" if username else None)
        if name and handle and name != handle:
            return f"{name} ({handle})"
        return name or handle or f"{who[:8]}…"


async def names(bot: SignalBot) -> Names:
    """The names the bot knows, and the phone numbers it knows people by."""
    found = Names()
    for kept in (allowed_list, admin_list):
        found.update({e.id: e.note for e in kept.current().entries if e.note})
    try:
        for recipient in await fetch_recipients():
            if recipient.number and recipient.uuid:
                found.numbers[recipient.uuid] = recipient.number
            if recipient.username and recipient.uuid:
                found.usernames[recipient.uuid] = recipient.username
            if name := recipient.real_name:
                found.update(
                    {who: name for who in (recipient.number, recipient.uuid) if who}
                )
    except Exception as e:
        logger.warning("Could not look up the names: %s", describe(e))
    found.update({group.id: group.name for group in bot.groups if group.name})
    return found


# Linking the phone numbers on the lists to the people they're of


class Found(BaseModel):
    """A phone number in Signal's answer to a look-up."""

    number: str = ""
    registered: bool = False  # found: signal-cli knows whose it is now


FOUND = TypeAdapter(list[Found])

# The phone numbers looked up since the start: each once, as Signal limits
# how many an account looks up
looked_up: set[str] = set()


async def link(numbers: Collection[str]) -> None:
    """Look up those of the phone numbers that signal-cli can't put a Signal
    ID to, and that weren't looked up since the start, so it knows whose
    they are. Never raises."""
    wanted = {n for n in numbers if re.match(PHONE_NUMBER, n)}
    wanted -= looked_up | {get_settings().account}
    if not wanted:
        return
    try:
        known = {c.number for c in await fetch_recipients() if c.number and c.uuid}
        if not (unknown := sorted(wanted - known)):
            return
        found = FOUND.validate_python(await rest.look_up(unknown))
    except Exception as e:
        logger.warning("Could not look up phone numbers: %s", describe(e))
        return
    looked_up.update(unknown)
    linked = {each.number for each in found if each.registered}
    logger.info(
        "Looked up %d phone numbers: Signal found %d", len(unknown), len(linked)
    )
    if missing := [n for n in unknown if n not in linked]:
        # Not on Signal, or kept from being found by number
        logger.debug("Not found: %s", ", ".join(missing))


async def link_lists(bot: SignalBot) -> None:
    """Link the phone numbers on the lists, then write the names now known
    after the # of their lines with none."""
    await bot.wait_until_ready()
    logger.debug("Linking the phone numbers on the lists")
    await link(recipients())
    known = await names(bot)
    for kept in (allowed_list, admin_list):
        try:
            if count := kept.name(known):
                logger.info("Wrote %d names in %s", count, kept.path)
        except OSError as e:
            logger.error("Could not write the names in %s: %r", kept.path, e)


def start(bot: SignalBot) -> None:
    """Link the phone numbers on the lists once signalbot is ready."""
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        link_lists,
        args=[bot],
        id="link-numbers",
        misfire_grace_time=None,
        replace_existing=True,
    )
