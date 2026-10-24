"""Specials: the admins' own commands that post several things in one go,
each after the one before: texts, and what other commands answer. The
admins make them in a direct chat with the bot:

  /special add /morning Good morning! /today + /weather; /uniquephoto
  /special add /bins The bins go out tonight!
  /specials                    the admins' own
  /special shortcuts /morning /gm   other names for /morning
  /special shortcuts /morning -     none
  /special remove /bins

A special's parts are separated by ; or line breaks. Text before a command
heads the command's first answer, a blank line between; text alone is a
message of its own. A + of its own in place of a ; puts all that the parts
on either side of it post in one message, a blank line between: /today +
/weather is the day with the weather under it. A + in a word, as in C++, is
text. The commands run as a timer runs them, as an admin would
in a direct chat with the bot, so a special can have any command a timer
can, but not another special. Specials are for timers, /run and the admins,
in a direct chat. Text keeps the formatting the admin gives it in Signal:
bold, italic, strikethrough, monospace and spoiler.

A special's shortcuts are other names for it, as an album's are for /photo
with the album: each a word, with or without a / first, but not a name the
bot answers to already. Timers keep a special by its name, whichever they
were given.

They're kept in data_dir/specials.txt, one per line, the name and its
shortcuts first, their commands by their English names, as the timers file
keeps them, their texts in signal-cli-rest-api's marks for the formatting
(styles.py). It can be changed by hand: the bot reads it again when it
changes, and leaves comments and lines it can't read as they are. A special
a timer runs can be changed, with /special add, but not removed.
"""

import logging
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Self

from signalbot import DataMessageContext, SendMessage, TextMode, TextStyle

from .commands import (
    COMMAND_START,
    Command,
    Edits,
    Handler,
    aliases,
    answer,
    built_in,
    canonical,
    shortcut_clash,
    undo_with,
)
from .config import get_settings, slashed
from .files import write_privately
from .i18n import _, ngettext, prefixed
from .messages import PerChat, escape, for_chat, unreadable_text
from .photos import REMOVE
from .styles import Styles, marked, styles_of
from .timers import check_commands, timekeeper

logger = logging.getLogger(__name__)

MAX_SPECIALS = 50
# Few, as a timer may run several specials, and each part posts to each of
# its chats
MAX_PARTS = 5
MAX_SHORTCUTS = 5  # a special's, as an album's
NAME = re.compile(r"^/[^\s|;]+$")
# What separates a special's parts: a ; or a line break, or a + of its own,
# which keeps the parts on either side of it in one message
SEPARATOR = re.compile(r"([;\n]|(?<!\S)\+(?!\S))")

HEADER = (
    "# nejomibot's specials, one per line:",
    "#   name and its shortcuts | its parts, separated by ;, or by + for one message",
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
    joined: bool = False  # by a + to the part before, in its message


type Parts = tuple[Part, ...]


def by_message(parts: Parts) -> list[Parts]:
    """The parts of each message: a part's own, and those joined to it."""
    found: list[Parts] = []
    for part in parts:
        if part.joined and found:
            found[-1] += (part,)
        else:
            found.append((part,))
    return found


def parts_text(parts: Parts, *, styled: bool = False) -> str:
    """As the file keeps them, or styled, as the bot shows them: their texts
    are in marks either way."""

    def command(text: str) -> str:
        return escape(prefixed(text)) if styled else text

    return "; ".join(
        " + ".join(f"{part.text} {command(part.command)}".strip() for part in one)
        for one in by_message(parts)
    )


def check_name(name: str) -> str | None:
    """Why a special can't have the name, if it can't."""
    if not NAME.match(name):
        return _("Give it a name: a word that starts with . or /, like /morning.")
    if built_in(name) or name.casefold() in aliases():
        return _("{name} is a command already.").format(name=prefixed(name))
    return None


def parse_parts(
    text: str, own: Collection[str], styles: Styles | None = None
) -> Parts | str:
    """The parts in the text, separated by ; or line breaks, or by a + of its
    own, which joins them: each its text, then its command, from the first
    word that starts with a / or a . (COMMAND_START). The text is a
    message's, with the styles of its characters, or without them, in marks
    already, as the file keeps it. Or why they can't be a special's: own are
    the names of the admins' specials, which a special can't run."""
    if styles is not None and "|" in text:
        return _("A special can't have a |: the file of specials uses it.")
    parts: list[Part] = []
    joins = False  # a + since the part before, even across a line break
    end = 0
    # Every other piece is a separator, the first a part
    for i, piece in enumerate(SEPARATOR.split(text)):
        at, end = end, end + len(piece)
        if i % 2:
            joins = joins or piece == "+"
            continue
        if not (stripped := piece.lstrip()):
            continue
        at += len(piece) - len(stripped)
        start = COMMAND_START.search(stripped)
        words = stripped[: start.start() if start else None].rstrip()
        if (
            styles is not None
            and (words := marked(words, styles[at : at + len(words)])) is None
        ):
            return _(
                "That formatting can't be kept: bold and italic can't meet "
                "inside a word, nor a style start or end right by a \\ or *."
            )
        command = ""
        if start is not None:
            command = canonical(stripped[start.start() :].strip())
            if command.split()[0].lower() in own:
                return _(
                    "{command} is a special of yours, and specials can't run "
                    "each other."
                ).format(command=prefixed(command))
            # built_in, as known() would read the file this may be reading
            if why_not := check_commands([command], built_in):
                return why_not
        parts.append(Part(words, command, joins and bool(parts)))
        joins = False
    if not parts:
        return _("What should it post?") + f"\n\n{usage()}"
    if len(parts) > MAX_PARTS:
        return _("A special has at most {count} parts.").format(count=MAX_PARTS)
    return tuple(parts)


type Shortcuts = tuple[str, ...]  # each a word, with or without a / first


def names_on(line: str) -> list[str]:
    """The names on a line of the file, before its |: the special's, then its
    shortcuts."""
    return line.partition("|")[0].split()


def name_of(line: str) -> str:
    """The special's name on a line of the file."""
    return (names_on(line) or [""])[0].lower()


def line_of(name: str, parts: Parts, shortcuts: Shortcuts) -> str:
    return f"{' '.join((name, *shortcuts))} | {parts_text(parts)}"


def parse_line(line: str, own: Collection[str]) -> tuple[str, Parts, Shortcuts]:
    """A line of the file: a special's name, its parts and its shortcuts.
    Raises ValueError."""
    if "|" not in line:
        raise ValueError("no |")
    if why_not := check_name(name := name_of(line)):
        raise ValueError(why_not)
    shortcuts = tuple(names_on(line)[1:])
    # Which it would hide
    if taken := [each for each in shortcuts if built_in(each) or each.lower() in own]:
        raise ValueError(f"{taken[0]} is a command")
    if isinstance(parts := parse_parts(line.partition("|")[2], own), str):
        raise ValueError(parts)
    return name, parts, shortcuts


class OwnSpecials:
    """The admins' own specials, as their file has them."""

    def __init__(self) -> None:
        self.lines: list[str] = []  # the file's, all of them
        self.specials: dict[str, Parts] = {}  # by name
        self.shortcuts: dict[str, Shortcuts] = {}  # by the special's name
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
        shortcuts: dict[str, Shortcuts] = {}
        broken: list[str] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                name, parts, its_shortcuts = parse_line(line, names)
                if name in specials:
                    raise ValueError(f"a second {name}")
            except ValueError as e:
                # Its text is the admins' message: only at DEBUG
                logger.error("Specials line %d left alone, as it can't be read", number)
                logger.debug("Specials line %d: %s", number, e)
                broken.append(line)
                continue
            specials[name] = parts
            if its_shortcuts:
                shortcuts[name] = its_shortcuts
        self.lines, self.specials, self.broken = lines, specials, broken
        self.shortcuts = shortcuts

    def save(self, lines: list[str]) -> None:
        """Write the lines to the file, and make them the specials. Raises
        OSError, and then changes neither."""
        path = get_settings().specials_file
        write_privately(path, "\n".join(lines) + "\n")
        stat = path.stat()
        # Seen before they're read, as reading them looks up the shortcuts,
        # which would read the file again
        self.seen = (stat.st_mtime_ns, stat.st_size)
        self.take(lines)

    def add(self, name: str, parts: Parts, shortcuts: Shortcuts | None = None) -> None:
        """Add the special, last, or change it, with the shortcuts, or else
        those it has. Raises OSError."""
        found = self.current()
        if shortcuts is None:
            shortcuts = found.shortcuts.get(name, ())
        kept = [line for line in found.lines or HEADER if name_of(line) != name]
        self.save([*kept, line_of(name, parts, shortcuts)])

    def remove(self, name: str) -> None:
        """Raises OSError."""
        self.save([line for line in self.current().lines if name_of(line) != name])

    def command(self, text: str) -> Command | None:
        """The special the text is, if any: its name alone, in any case."""
        name = text.lower()
        return Command(name) if name in self.current().specials else None


own_specials = OwnSpecials()


def joined(messages: Sequence[SendMessage]) -> SendMessage:
    """The messages as one: their texts in order, a blank line between,
    styled if any is, and their photos; and each chat's own text, for a
    message with some (PerChat), as /today's. The bot's answers have
    nothing else."""
    if len(messages) == 1:
        return messages[0]
    styled = any(message.text_mode == TextMode.STYLED for message in messages)

    def text(chat: str = "") -> str:
        texts: list[str] = []
        for message in messages:
            own = (for_chat(message, chat) if chat else message).text or ""
            if styled and message.text_mode != TextMode.STYLED:
                own = escape(own)
            texts += [own] if own else []
        return "\n\n".join(texts)

    chats = {
        chat for each in messages if isinstance(each, PerChat) for chat in each.texts
    }
    photos = [photo for each in messages for photo in each.base64_attachments or []]
    mode = TextMode.STYLED if styled else None
    if chats:
        texts = {chat: text(chat) for chat in chats}
        return PerChat(
            text=text(), texts=texts, base64_attachments=photos or None, text_mode=mode
        )
    return SendMessage(text=text(), base64_attachments=photos or None, text_mode=mode)


async def posts(parts: Parts) -> list[SendMessage]:
    """What a special posts, part after part: what its command answers, the
    first headed by its text, or the text alone; and in one message, all
    that parts joined by + post."""
    found: list[SendMessage] = []
    for one in by_message(parts):
        answers: list[SendMessage] = []
        for part in one:
            own = await timekeeper.answers_to(part.command) if part.command else []
            if part.text:
                heading = SendMessage(text=part.text, text_mode=TextMode.STYLED)
                own[:1] = [joined([heading, *own[:1]])]
            answers += own
        found += [joined(answers)] if len(one) > 1 and answers else answers
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
            "  "
            + _(
                "A + in place of a ; puts the parts on either side of it in one "
                "message, as in /today + /weather."
            ),
            "  " + _("Text keeps the formatting you give it in Signal, such as bold."),
            _(
                "/special shortcuts <name> <names>: other names for one, such as "
                "/special shortcuts /morning /gm; with -, none"
            ),
            _("/special remove <name>: remove one"),
        ]
    )


def shortcuts_shown(name: str) -> str:
    """The special's shortcuts, as its line in /specials ends with them, if
    it has any. Styled."""
    if shortcuts := own_specials.current().shortcuts.get(name):
        return f" · 🏷️ {escape(' '.join(map(prefixed, shortcuts)))}"
    return ""


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
        f"**{escape(prefixed(name))}** · {parts_text(parts, styled=True)}"
        f"{shortcuts_shown(name)}"
        for name, parts in sorted(found.specials.items())
    ]
    if found.broken:
        lines.append(escape(unreadable_text(found.broken)))
    return "\n".join(lines)


def add_special(text: str, styles: Iterable[TextStyle] | None) -> str:
    """Add the special /special add describes, or change it; or say why it
    can't be. styles are the message's. Styled."""
    words = text.split(maxsplit=3)
    name = slashed(words[2]).lower() if len(words) > 2 else ""
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
    done = done.format(name=prefixed(name))
    return f"✅ **{escape(done)}**\n{parts_text(parts, styled=True)}"


def timers_running(name: str) -> list[int]:
    """The numbers of the timers that run the special."""
    timekeeper.reread()
    return sorted(
        timer.id
        for timer in timekeeper.timers.values()
        if any(command.split()[0].lower() == name for command in timer.commands)
    )


def special_named(name: str) -> tuple[str, Parts | None] | str:
    """The special given by its name, with or without its /, and its parts,
    None if there's no such special; or why the name is missing."""
    if not name:
        return _("Which special? Give its name, as /specials shows.")
    name = "/" + slashed(name).lower().removeprefix("/")
    return name, own_specials.current().specials.get(name)


def remove_special(name: str) -> str:
    """Remove the special, unless a timer runs it; or say why not. Styled."""
    if isinstance(found := special_named(name), str):
        return escape(found)
    name, parts = found
    if parts is None:
        return escape(_("There's no special {name}.").format(name=prefixed(name)))
    if running := timers_running(name):
        return escape(
            ngettext(
                "Timer {timers} runs it: remove that first, or change the special.",
                "Timers {timers} run it: remove those first, or change the special.",
                len(running),
            ).format(timers=", ".join(f"#{n}" for n in running))
        )
    shortcuts = own_specials.current().shortcuts.get(name, ())
    own_specials.remove(name)
    undo_with(lambda: own_specials.add(name, parts, shortcuts))
    removed = _("Removed {name}").format(name=prefixed(name))
    return f"🗑️ **{escape(removed)}**\n{parts_text(parts, styled=True)}"


def set_shortcuts(name: str, words: list[str]) -> str:
    """Make the words the special's shortcuts, or with -, take them away; for
    an edit to undo. Or say why not."""
    if isinstance(found := special_named(name), str):
        return found
    name, parts = found
    if parts is None:
        return _("There's no special {name}.").format(name=prefixed(name))
    if not words:
        return usage()
    previous = own_specials.current().shortcuts.get(name, ())
    if words == [REMOVE]:
        if not previous:
            return _("{album} has no shortcuts.").format(album=prefixed(name))
        shortcuts: Shortcuts = ()
        done = _("✅ {album}: no shortcuts.").format(album=prefixed(name))
    else:
        shortcuts = tuple(dict.fromkeys(map(slashed, words)))
        if len(shortcuts) > MAX_SHORTCUTS:
            return _("A special has at most {count} shortcuts.").format(
                count=MAX_SHORTCUTS
            )
        for shortcut in shortcuts:
            if why_not := shortcut_clash(shortcut, name):
                return why_not
        done = _("✅ Shortcuts for {name}: {shortcuts}.").format(
            name=prefixed(name), shortcuts=", ".join(map(prefixed, shortcuts))
        )
    own_specials.add(name, parts, shortcuts)
    undo_with(lambda: own_specials.add(name, parts, previous))
    return done


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
    if action == "shortcuts":
        return escape(set_shortcuts(words[2] if len(words) > 2 else "", words[3:]))
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
            subcommands=("add", "remove", "list", "shortcuts"),
        ),
    )

    @classmethod
    def takes(cls, text: str) -> Command | None:
        """The admins' own specials too, by name."""
        return super().takes(text) or own_specials.command(text)

    @classmethod
    def shortcuts(cls) -> dict[str, str]:
        """The specials' shortcuts, each for its special."""
        found = own_specials.current().shortcuts
        return {
            each.casefold(): name for name, names in found.items() for each in names
        }

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
