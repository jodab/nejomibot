"""Who may use the bot.

The admins, listed in the config, may use every command; the admin commands
only in a direct chat with the bot. Everyone else may use the everyday
commands if they're on the allowed list: a contact, in a direct chat with the
bot, or a group, where anyone in it may use them, there.

The allowed list is a file, data_dir/allowed.txt: a phone number, Signal
ID or group ID a line, and after a # who that is. The admins see it with
/allowed and change it with /allow and /disallow (allowed.py). It can be
changed by hand too: the bot rereads it when it changes, and leaves comments
and lines it can't read as they are. Without the file, the bot starts an
empty one; in debug mode, one with just debug_group.

The admins aren't on the list: they're in the config, so no command can take
away what they may do.
"""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from signalbot import DataMessage, SignalBot

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
    "# Who may use nejomibot's everyday commands, besides the admins in its",
    "# config: a phone number, Signal ID or group ID per line, and after a #",
    "# who that is. Changed with /allow and /disallow in Signal, or by hand:",
    "# the bot rereads it, and leaves comments and other lines as they are.",
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
    """The allowed list, as its file has it."""

    def __init__(self) -> None:
        self.lines: list[str] = []  # the file's, all of them
        self.entries: list[Entry] = []  # each chat once, in the file's order
        self.broken: list[str] = []  # lines that can't be read
        self.path: Path | None = None  # the file read
        self.seen: tuple[int, int] | None = None  # its mtime and size, if read
        self.checked = 0.0  # when the file was last looked at, monotonic

    @property
    def ids(self) -> set[str]:
        return {entry.id for entry in self.entries}

    def take(self, lines: list[str]) -> None:
        """Make the lines the list."""
        entries: dict[str, Entry] = {}
        broken: list[str] = []
        for number, line in enumerate(lines, start=1):
            try:
                entry = parse(line)
            except ValueError as e:
                # The line may be someone's number: /allowed shows it
                logger.error("Line %d left alone, as it can't be read", number)
                logger.debug("Line %d: %s", number, e)
                broken.append(line)
                continue
            if entry is not None:
                entries.setdefault(entry.id, entry)
        self.lines, self.entries, self.broken = lines, list(entries.values()), broken

    def read(self) -> None:
        """Read the file, or make it if there's none. If it can't be read, the
        list stays as it was."""
        path = self.path = get_settings().allowed_file
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
        """Start the file: empty, or in debug mode, with just debug_group."""
        settings = get_settings()
        debug_group = settings.debug_group if settings.debug else None
        lines = [*HEADER, *([debug_group] if debug_group else [])]
        try:
            self.save(lines)
        except OSError as e:
            logger.error("Could not make %s, so the list is empty: %r", self.path, e)
            self.take(lines)
            self.seen = None  # not tried again until a file turns up
            return
        logger.info("Made %s: %d chats", self.path, len(self.ids))

    def save(self, lines: list[str]) -> None:
        """Write the lines to the file, and make them the list. Raises OSError,
        and then changes neither."""
        path = self.path = get_settings().allowed_file
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


allowed_list = AllowedList()


def is_admin(message: DataMessage) -> bool:
    admins = get_settings().admins
    return any(who in admins for who in (message.source_number, message.source_uuid))


def permits(bot: SignalBot, message: object) -> bool:
    """Whether the message's sender may use the everyday commands where they
    sent it: an admin or a contact on the list in a direct chat, anyone in a
    group on the list."""
    if not isinstance(message, DataMessage):
        return False
    allowed = allowed_list.current().ids
    if message.is_group():
        return bot.groups.get_id(message.source_or_group_id()) in allowed
    return is_admin(message) or any(
        who in allowed for who in (message.source_number, message.source_uuid) if who
    )


def recipients() -> list[str]:
    """Every contact and group the bot is set up to talk to: those in the
    config, and on the allowed list."""
    return sorted({*get_settings().configured_recipients, *allowed_list.current().ids})


async def names(bot: SignalBot) -> dict[str, str]:
    """The names of the groups the bot is in, by ID, and of the people
    signal-cli knows by name, by phone number and Signal ID."""
    found: dict[str, str] = {}
    try:
        for recipient in await fetch_recipients():
            if name := recipient.real_name:
                found.update(
                    {who: name for who in (recipient.number, recipient.uuid) if who}
                )
    except Exception as e:
        logger.warning("Could not look up the names: %s", describe(e))
    found.update({group.id: group.name for group in bot.groups if group.name})
    return found
