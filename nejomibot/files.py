"""The files the bot keeps what it's told in, and what it's done: the timers,
the specials, the allowed list, the admins added, the reminders, the lists,
the birthdays, the albums' birth dates, the chats' languages, the photos
sent and the messages waiting to be sent. They list phone numbers, so only
the bot's user may read them."""

import contextlib
import logging
import os
import tempfile
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Self

from .config import get_settings

logger = logging.getLogger(__name__)


def write_privately(path: Path, text: str) -> None:
    """Replace the file with the text, as replace_privately does."""
    replace_privately(path, lambda f: f.write(text.encode()))


def replace_privately[T](path: Path, write: Callable[[BinaryIO], T]) -> T:
    """Replace the file with what write() writes, and return what it does:
    through a temp file beside it, only the bot's user's, so it's never read
    half written, and on disk before it replaces the file, so a power cut
    can't leave it empty. Raises OSError, and then leaves the file as it
    was."""
    fd, name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".part"
    )
    part = Path(name)
    try:
        if os.geteuid() == 0:
            # As when nejomibot-account runs as root: the file stays whose it
            # was, or a new one its folder's, so the bot can still read it
            try:
                owner = path.stat()
            except FileNotFoundError:
                owner = path.parent.stat()
            os.fchown(fd, owner.st_uid, owner.st_gid)
        with os.fdopen(fd, "wb") as f:
            written = write(f)
            f.flush()
            os.fsync(f.fileno())
        part.replace(path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    # The new name, too; a file system that can't sync a folder keeps it anyway
    with contextlib.suppress(OSError):
        folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    return written


def append_privately(path: Path, line: str) -> None:
    """Add a line to the file, or start it. Raises OSError."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        os.fchmod(fd, 0o600)  # if it was made before, with another mode
        f.write(f"{line}\n")


@dataclass(frozen=True)
class Change:
    """A change made to a file of lines, to undo."""

    added: tuple[str, ...]  # the lines put last
    removed: tuple[tuple[int, str], ...]  # the lines taken out, and where they were


class KeptLines[T]:
    """A file in data_dir with a T on each line, such as the reminders. It
    can be changed by hand: the bot reads it again when it changes, which a
    stat tells, quickly enough for every command, and leaves comments and
    lines it can't read as they are. If it can't be read, what the bot has
    stays as it was."""

    def __init__(
        self,
        name: str,  # in data_dir, or in folder
        header: Sequence[str],  # the comments a new file starts with
        parse: Callable[[str], T],  # a line; raises ValueError
        line_of: Callable[[T], str],
        folder: Callable[[], Path] | None = None,  # where it is, if not data_dir
    ) -> None:
        self.name = name
        self.header = list(header)
        self.parse = parse
        self.line_of = line_of
        self.folder = folder
        self.reset()

    def path(self) -> Path:
        if self.folder is not None:
            return self.folder() / self.name
        return get_settings().data_file(self.name)

    def reset(self) -> None:
        """As at a start, with nothing read yet."""
        self.lines: list[str] = []  # the file's, all of them
        self.found: list[tuple[int, T]] = []  # what lines have, by their index
        self.broken: list[str] = []  # lines that can't be read
        self.seen: tuple[int, int] | None = None  # the file's mtime and size

    @property
    def entries(self) -> list[T]:
        """What the lines it can read have, in the file's order."""
        return [entry for _index, entry in self.found]

    def current(self) -> Self:
        """What the file has, read again if it has changed."""
        path = self.path()
        try:
            stat = path.stat()
        except FileNotFoundError:
            if self.seen is not None:  # it was there
                self.take([])
                self.seen = None
            return self
        except OSError:
            return self  # can't tell
        if (stat.st_mtime_ns, stat.st_size) != self.seen:
            # Seen, even if it can't be read, so the error is logged once
            self.seen = (stat.st_mtime_ns, stat.st_size)
            try:
                self.take(path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeError) as e:
                logger.error("Could not read %s, so it stays as it was: %r", path, e)
        return self

    def take(self, lines: list[str]) -> None:
        """Make the lines what the file has."""
        found: list[tuple[int, T]] = []
        broken: list[str] = []
        for index, line in enumerate(lines):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                found.append((index, self.parse(line)))
            except ValueError as e:
                # What it says may be someone's: only at DEBUG
                logger.error(
                    "%s line %d left alone, as it can't be read", self.name, index + 1
                )
                logger.debug("%s line %d: %s", self.name, index + 1, e)
                broken.append(line)
        self.lines, self.found, self.broken = lines, found, broken

    def save(self, lines: list[str]) -> None:
        """Write the lines to the file, and make them what it has. Raises
        OSError, and then changes neither."""
        path = self.path()
        write_privately(path, "\n".join(lines) + "\n")
        stat = path.stat()
        self.take(lines)
        self.seen = (stat.st_mtime_ns, stat.st_size)

    def add(self, *entries: T) -> Change:
        """Add the entries, last. Raises OSError."""
        return self.current().change((), entries)

    def remove(self, entries: Collection[T]) -> Change:
        """Take out the lines of these entries, as entries last gave them.
        Raises OSError."""
        return self.change(entries)

    def change(self, gone: Collection[T], added: Sequence[T] = ()) -> Change:
        """Take out the lines of what's gone, as entries last gave them, and
        add what's added, last, in one write. Raises OSError."""
        out = {i for i, entry in self.found if any(entry is e for e in gone)}
        removed = tuple((i, self.lines[i]) for i in sorted(out))
        kept = [line for i, line in enumerate(self.lines) if i not in out]
        new = tuple(map(self.line_of, added))
        self.save([*(kept if self.lines else self.header), *new])
        return Change(new, removed)

    def replace(self, old: T, new: T) -> None:
        """Write new's line in the place of old's, as entries last gave it.
        Raises OSError, and ValueError if old isn't among them."""
        index = next((i for i, entry in self.found if entry is old), None)
        if index is None:
            raise ValueError("not among the entries")
        lines = list(self.lines)
        lines[index] = self.line_of(new)
        self.save(lines)

    def revert(self, change: Change) -> None:
        """Undo the change, as far as the file still has it: take out the
        lines it added, the last of each, and put those it took out back
        where they were. Raises OSError."""
        lines = list(self.current().lines)
        for line in reversed(change.added):
            if line in lines:
                del lines[len(lines) - 1 - lines[::-1].index(line)]
        for index, line in change.removed:
            lines.insert(min(index, len(lines)), line)
        self.save(lines)
