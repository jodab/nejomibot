"""Specials: the admins' own commands that post several things in one go,
each after the one before: texts, and what other commands answer. The
admins make them in a direct chat with the bot:

  /special add /morning Good morning! /today; /photo new
  /special add /bins The bins go out tonight!
  /specials                    the admins' own
  /special remove /bins

A special's parts are separated by ; or line breaks. Text before a command
heads the command's first answer, a blank line between; text alone is a
message of its own. The commands run as a timer runs them, as an admin would
in a direct chat with the bot, so a special can have any command a timer
can, but not another special. Specials are for timers, /run and the admins,
in a direct chat. Text keeps the formatting the admin gives it in Signal:
bold, italic, strikethrough, monospace and spoiler.

They're kept in data_dir/specials.txt, one per line, their commands by their
English names, as the timers file keeps them, their texts in
signal-cli-rest-api's marks for the formatting (styles.py). It can be
changed by hand: the bot reads it again when it changes, and leaves comments
and lines it can't read as they are. A special a timer runs can be changed,
with /special add, but not removed.
"""

import logging
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Self

from signalbot import DataMessageContext, SendMessage, TextMode, TextStyle

from .commands import (
    Command,
    Edits,
    Handler,
    aliases,
    answer,
    built_in,
    canonical,
    undo_with,
)
from .config import get_settings
from .files import write_privately
from .i18n import _, ngettext
from .messages import PerChat, escape, unreadable_text
from .styles import Styles, marked, styles_of
from .timers import check_commands, timekeeper

logger = logging.getLogger(__name__)

MAX_SPECIALS = 50
# Few, as a timer may run several specials, and each part posts to each of
# its chats
MAX_PARTS = 5
NAME = re.compile(r"^/[^\s|;]+$")

HEADER = (
    "# nejomibot's specials, one per line:",
    "#   name | its parts, separated by ;",
    "# Texts in marks: **bold**, *italic*, ~strikethrough~, `monospace`, ||spoiler||,",
    "# a \\ before a *, ~, ` or | that shows as it is.",
    "# Changed with /special in Signal, or by hand: the bot reads it again when",
    "# it changes, and leaves comments and lines it can't read as they are.",
)


@dataclass(frozen=True)
class Part:
    """A part of a special: text, a command, or text that heads the command's
    first answer."""

    text: str = ""  # in marks for its styles
    command: str = ""  # by its English name


type Parts = tuple[Part, ...]


def parts_text(parts: Parts, *, styled: bool = False) -> str:
    """As the file keeps them, or styled, as the bot shows them: their texts
    are in marks either way."""
    command = escape if styled else str
    return "; ".join(f"{part.text} {command(part.command)}".strip() for part in parts)


def check_name(name: str) -> str | None:
    """Why a special can't have the name, if it can't."""
    if not NAME.match(name):
        return _("Give it a name: a word that starts with /, like /morning.")
    if built_in(name) or name.casefold() in aliases():
        return _("{name} is a command already.").format(name=name)
    return None


def parse_parts(
    text: str, own: Collection[str], styles: Styles | None = None
) -> Parts | str:
    """The parts in the text, separated by ; or line breaks: each its text,
    then its command, from the first word that starts with /. The text is a
    message's, with the styles of its characters, or without them, in marks
    already, as the file keeps it. Or why they can't be a special's: own are
    the names of the admins' specials, which a special can't run."""
    if styles is not None and "|" in text:
        return _("A special can't have a |: the file of specials uses it.")
    parts: list[Part] = []
    for piece in re.finditer(r"[^\s;][^;\n]*", text):
        start = re.search(r"(?:^|\s)/", piece[0])
        words = piece[0][: start.start() if start else None].rstrip()
        if styles is not None:
            at = piece.start()
            if (words := marked(words, styles[at : at + len(words)])) is None:
                return _(
                    "That formatting can't be kept: bold and italic can't meet "
                    "inside a word, nor a style start or end right by a \\ or *."
                )
        if start is None:
            parts.append(Part(words))
            continue
        command = canonical(piece[0][start.start() :].strip())
        if command.split()[0].lower() in own:
            return _(
                "{command} is a special of yours, and specials can't run each other."
            ).format(command=command)
        # built_in, as known() would read the file this may be reading
        if why_not := check_commands([command], built_in):
            return why_not
        parts.append(Part(words, command))
    if not parts:
        return _("What should it post?") + f"\n\n{usage()}"
    if len(parts) > MAX_PARTS:
        return _("A special has at most {count} parts.").format(count=MAX_PARTS)
    return tuple(parts)


def name_of(line: str) -> str:
    """The name on a line of the file: what comes before its |."""
    return line.partition("|")[0].strip().lower()


def parse_line(line: str, own: Collection[str]) -> tuple[str, Parts]:
    """A line of the file: a special's name, and its parts. Raises ValueError."""
    if "|" not in line:
        raise ValueError("no |")
    if why_not := check_name(name := name_of(line)):
        raise ValueError(why_not)
    if isinstance(parts := parse_parts(line.partition("|")[2], own), str):
        raise ValueError(parts)
    return name, parts


class OwnSpecials:
    """The admins' own specials, as their file has them."""

    def __init__(self) -> None:
        self.lines: list[str] = []  # the file's, all of them
        self.specials: dict[str, Parts] = {}  # by name
        self.broken: list[str] = []  # lines that can't be read
        self.seen: tuple[int, int] | None = None  # the file's mtime and size

    def current(self) -> Self:
        """The specials, read again if the file has changed, which a stat
        tells, quickly enough for every command. If the file can't be read,
        they stay as they were."""
        path = get_settings().specials_file
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
                logger.error(
                    "Could not read %s, the specials stay as they were: %r", path, e
                )
        return self

    def take(self, lines: list[str]) -> None:
        """Make the lines the specials."""
        names = set(map(name_of, lines))
        specials: dict[str, Parts] = {}
        broken: list[str] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                name, parts = parse_line(line, names)
                if name in specials:
                    raise ValueError(f"a second {name}")
            except ValueError as e:
                # Its text is the admins' message: only at DEBUG
                logger.error("Specials line %d left alone, as it can't be read", number)
                logger.debug("Specials line %d: %s", number, e)
                broken.append(line)
                continue
            specials[name] = parts
        self.lines, self.specials, self.broken = lines, specials, broken

    def save(self, lines: list[str]) -> None:
        """Write the lines to the file, and make them the specials. Raises
        OSError, and then changes neither."""
        path = get_settings().specials_file
        write_privately(path, "\n".join(lines) + "\n")
        stat = path.stat()
        self.take(lines)
        self.seen = (stat.st_mtime_ns, stat.st_size)

    def add(self, name: str, parts: Parts) -> None:
        """Add the special, last, or change it. Raises OSError."""
        lines = self.current().lines or list(HEADER)
        kept = [line for line in lines if name_of(line) != name]
        self.save([*kept, f"{name} | {parts_text(parts)}"])

    def remove(self, name: str) -> None:
        """Raises OSError."""
        self.save([line for line in self.current().lines if name_of(line) != name])

    def command(self, text: str) -> Command | None:
        """The special the text is, if any: its name alone, in any case."""
        name = text.lower()
        return Command(name) if name in self.current().specials else None


own_specials = OwnSpecials()


def headed(text: str, message: SendMessage) -> SendMessage:
    """The message, styled, the text in marks before its own, a blank line
    between; in each chat's text too, for a message with some."""

    def head(own: str) -> str:
        if message.text_mode != TextMode.STYLED:
            own = escape(own)
        return f"{text}\n\n{own}" if own else text

    update: dict[str, object] = {
        "text": head(message.text or ""),
        "text_mode": TextMode.STYLED,
    }
    if isinstance(message, PerChat):
        update["texts"] = {chat: head(own) for chat, own in message.texts.items()}
    return message.model_copy(update=update)


async def posts(parts: Parts) -> list[SendMessage]:
    """What a special posts, part after part: what its command answers, the
    first headed by its text, or the text alone."""
    found: list[SendMessage] = []
    for part in parts:
        answers = await timekeeper.answers_to(part.command) if part.command else []
        if part.text and answers:
            answers[0] = headed(part.text, answers[0])
        elif part.text:
            answers = [SendMessage(text=part.text, text_mode=TextMode.STYLED)]
        found += answers
    return found


# The commands


def usage() -> str:
    return "\n".join(
        [
            _("/specials: commands of your own, of text and other commands"),
            _("/special add <name> <parts>: a new one, or a change, e.g."),
            "  " + _("/special add /morning Good morning! /weather"),
            "  "
            + _(
                "Parts are separated by ; or line breaks. Text before a command "
                "heads its answer, text alone is a message."
            ),
            "  " + _("Text keeps the formatting you give it in Signal, such as bold."),
            _("/special remove <name>: remove one"),
        ]
    )


def list_specials() -> str:
    """The admins' own, and the lines of their file the bot can't read.
    Styled."""
    found = own_specials.current()
    if not found.specials and not found.broken:
        return escape(_("No specials of your own yet.") + f"\n\n{usage()}")
    count = len(found.specials)
    title = ngettext("✨ {count} special", "✨ {count} specials", count)
    lines = [f"**{escape(title.format(count=count))}**"]
    lines += [
        f"**{escape(name)}** · {parts_text(parts, styled=True)}"
        for name, parts in sorted(found.specials.items())
    ]
    if found.broken:
        lines.append(escape(unreadable_text(found.broken)))
    return "\n".join(lines)


def add_special(text: str, styles: Iterable[TextStyle] | None) -> str:
    """Add the special /special add describes, or change it; or say why it
    can't be. styles are the message's. Styled."""
    words = text.split(maxsplit=3)
    name = words[2].lower() if len(words) > 2 else ""
    if why_not := check_name(name):
        return escape(why_not)
    found = own_specials.current()
    given = words[3] if len(words) > 3 else ""
    given_styles = styles_of(text, styles)[len(text) - len(given) :]
    parts = parse_parts(given, {*found.specials, name}, given_styles)
    if isinstance(parts, str):
        return escape(parts)
    previous = found.specials.get(name)
    changed = previous is not None
    if not changed and len(found.specials) >= MAX_SPECIALS:
        return escape(
            _("There are {count} specials already: remove one first.").format(
                count=MAX_SPECIALS
            )
        )
    own_specials.add(name, parts)
    if previous is None:
        undo_with(lambda: own_specials.remove(name))
    else:
        undo_with(lambda: own_specials.add(name, previous))
    done = _("Changed {name}") if changed else _("Added {name}")
    return f"✅ **{escape(done.format(name=name))}**\n{parts_text(parts, styled=True)}"


def timers_running(name: str) -> list[int]:
    """The numbers of the timers that run the special."""
    timekeeper.reread()
    return sorted(
        timer.id
        for timer in timekeeper.timers.values()
        if any(command.split()[0].lower() == name for command in timer.commands)
    )


def remove_special(name: str) -> str:
    """Remove the special, unless a timer runs it; or say why not. Styled."""
    if not name:
        return escape(_("Which special? Give its name, as /specials shows."))
    name = "/" + name.lower().removeprefix("/")
    if (parts := own_specials.current().specials.get(name)) is None:
        return escape(_("There's no special {name}.").format(name=name))
    if running := timers_running(name):
        return escape(
            ngettext(
                "Timer {timers} runs it: remove that first, or change the special.",
                "Timers {timers} run it: remove those first, or change the special.",
                len(running),
            ).format(timers=", ".join(f"#{n}" for n in running))
        )
    own_specials.remove(name)
    undo_with(lambda: own_specials.add(name, parts))
    removed = _("Removed {name}").format(name=name)
    return f"🗑️ **{escape(removed)}**\n{parts_text(parts, styled=True)}"


def specials_answer(
    words: list[str], text: str, styles: Iterable[TextStyle] | None
) -> str:
    """What to answer /specials or /special: the list, or what changed.
    styles are the message's. Styled."""
    action = words[1].casefold() if len(words) > 1 else "list"
    if action == "list":
        return list_specials()
    if action == "add":
        return add_special(text, styles)
    if action == "remove":
        return remove_special(words[2] if len(words) > 2 else "")
    return escape(usage())


class Specials(Handler):
    """Runs the admins' specials, which an edit runs again, as their commands
    change nothing. /specials and /special list and change them; an edit of
    a change takes its place. Timers may run /specials alone, which only
    lists them, but not what changes them, as /specials with more after it
    does."""

    commands = (
        Command("/specials"),
        Command("/specials", more=True, timers=False, subcommands=("list",)),
        Command(
            "/special",
            more=True,
            timers=False,
            subcommands=("add", "remove", "list"),
        ),
    )

    @classmethod
    def takes(cls, text: str) -> Command | None:
        """The admins' own specials too, by name."""
        return super().takes(text) or own_specials.command(text)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = context.message.text or ""
        words = text.split()
        if command.name in ("/specials", "/special"):
            styles = context.message.text_styles
            await answer(
                context,
                lambda: specials_answer(words, text, styles),
                # Listing them runs again; an edit of a change takes its place
                edits=Edits.RUN_AGAIN
                if words[1:2] in ([], ["list"])
                else Edits.REPLACE,
                styled=True,
            )
        elif parts := own_specials.specials.get(command.name):
            # Their commands are what timers may run, which change nothing
            await answer(context, lambda: posts(parts), slow=True)
