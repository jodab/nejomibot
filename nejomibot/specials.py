"""Specials: commands that post several things in one go, each after the one
before: texts, and what other commands answer.

Two come with the bot: /dailypost, the weather, then the photo of the day,
captioned "Photo of the day!" (none twice until every photo has been sent,
so each run uses one up); and /dailyquote, a proverb or quote from
fortunes_svenska, headed "Proverb or quote of the day:". The admins make
their own, in a direct chat with the bot:

  /special add /morning Good morning! /weather; /dailyquote
  /special add /bins The bins go out tonight!
  /specials                    the admins' own
  /special remove /bins

A special's parts are separated by ; or line breaks. Text before a command
heads the command's first answer, a blank line between; text alone is a
message of its own. The commands run as a timer runs them, as an admin would
in a direct chat with the bot, so a special can have any command a timer
can, /dailypost and /dailyquote too, but not another of the admins' own.
Specials are for timers, /run and the admins, in a direct chat.

The admins' own are kept in data_dir/specials.txt, one per line, their
commands by their English names, as the timers file keeps them. It can be
changed by hand: the bot reads it again when it changes, and leaves comments
and lines it can't read as they are. A special a timer runs can be changed,
with /special add, but not removed.
"""

import asyncio
import logging
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Self

from signalbot import DataMessageContext, SendMessage, TextMode

from .commands import Command, Handler, Reply, aliases, answer, built_in, canonical
from .config import get_settings
from .files import write_privately
from .fortune import fortune_answer
from .i18n import _, ngettext
from .messages import escape, unreadable_text
from .photos import photo_message
from .timers import check_commands, timekeeper
from .weather import weather_message

logger = logging.getLogger(__name__)

MAX_SPECIALS = 50
# Few, as a timer may run several specials, and each part posts to each of
# its chats
MAX_PARTS = 5
NAME = re.compile(r"^/[^\s|;]+$")

HEADER = (
    "# nejomibot's specials, one per line:",
    "#   name | its parts, separated by ;",
    "# Changed with /special in Signal, or by hand: the bot reads it again when",
    "# it changes, and leaves comments and lines it can't read as they are.",
)


# The two the bot comes with


async def daily_post() -> list[Reply]:
    """The weather, then the photo of the day."""
    weather = await weather_message()
    return [weather, await photo_message(_("Photo of the day!"), track_sent=True)]


async def daily_quote() -> str:
    """A proverb or quote from fortunes_svenska, headed as the day's."""
    quote = await asyncio.to_thread(fortune_answer, "fortunes_svenska")
    return f"{_('Proverb or quote of the day:')}\n\n{quote}"


# The admins' own


@dataclass(frozen=True)
class Part:
    """A part of a special: text, a command, or text that heads the command's
    first answer."""

    text: str = ""
    command: str = ""  # by its English name

    def __str__(self) -> str:
        return f"{self.text} {self.command}".strip()


type Parts = tuple[Part, ...]


def parts_text(parts: Parts) -> str:
    """As the file keeps them, and the bot shows them."""
    return "; ".join(map(str, parts))


def check_name(name: str) -> str | None:
    """Why a special can't have the name, if it can't."""
    if not NAME.match(name):
        return _("Give it a name: a word that starts with /, like /morning.")
    if built_in(name) or name.casefold() in aliases():
        return _("{name} is a command already.").format(name=name)
    return None


def parse_parts(text: str, own: Collection[str]) -> Parts | str:
    """The parts in the text, separated by ; or line breaks: each its text,
    then its command, from the first word that starts with /. Or why they
    can't be a special's: own are the names of the admins' specials, which a
    special can't run."""
    if "|" in text:
        return _("A special can't have a |: the file of specials uses it.")
    parts: list[Part] = []
    for piece in filter(None, (piece.strip() for piece in re.split(r"[;\n]", text))):
        start = re.search(r"(?:^|\s)/", piece)
        if start is None:
            parts.append(Part(piece))
            continue
        command = canonical(piece[start.start() :].strip())
        if command.split()[0].lower() in own:
            return _(
                "{command} is a special of yours, and specials can't run each other."
            ).format(command=command)
        # built_in, as known() would read the file this may be reading
        if why_not := check_commands([command], built_in):
            return why_not
        parts.append(Part(piece[: start.start()].strip(), command))
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
    """The message, the text before its own, a blank line between."""
    if message.text_mode == TextMode.STYLED:
        text = escape(text)
    body = f"{text}\n\n{message.text}" if message.text else text
    return message.model_copy(update={"text": body})


async def posts(parts: Parts) -> list[SendMessage]:
    """What a special posts, part after part: what its command answers, the
    first headed by its text, or the text alone."""
    found: list[SendMessage] = []
    for part in parts:
        answers = await timekeeper.answers_to(part.command) if part.command else []
        if part.text and answers:
            answers[0] = headed(part.text, answers[0])
        elif part.text:
            answers = [SendMessage(text=part.text)]
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
        f"**{escape(name)}** · {escape(parts_text(parts))}"
        for name, parts in sorted(found.specials.items())
    ]
    if found.broken:
        lines.append(escape(unreadable_text(found.broken)))
    return "\n".join(lines)


def add_special(text: str) -> str:
    """Add the special /special add describes, or change it; or say why it
    can't be. Styled."""
    words = text.split(maxsplit=3)
    name = words[2].lower() if len(words) > 2 else ""
    if why_not := check_name(name):
        return escape(why_not)
    found = own_specials.current()
    parts = parse_parts(words[3] if len(words) > 3 else "", {*found.specials, name})
    if isinstance(parts, str):
        return escape(parts)
    changed = name in found.specials
    if not changed and len(found.specials) >= MAX_SPECIALS:
        return escape(
            _("There are {count} specials already: remove one first.").format(
                count=MAX_SPECIALS
            )
        )
    own_specials.add(name, parts)
    done = _("Changed {name}") if changed else _("Added {name}")
    return f"✅ **{escape(done.format(name=name))}**\n{escape(parts_text(parts))}"


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
    removed = _("Removed {name}").format(name=name)
    return f"🗑️ **{escape(removed)}**\n{escape(parts_text(parts))}"


def specials_answer(words: list[str], text: str) -> str:
    """What to answer /specials or /special: the list, or what changed.
    Styled."""
    action = words[1].casefold() if len(words) > 1 else "list"
    if action == "list":
        return list_specials()
    if action == "add":
        return add_special(text)
    if action == "remove":
        return remove_special(words[2] if len(words) > 2 else "")
    return escape(usage())


class Specials(Handler):
    """Runs the specials: /dailypost and /dailyquote, which an edit runs again,
    and the admins' own, which it doesn't, as their commands may change
    something. /specials and /special list and change the admins' own:
    neither timers nor edits run those, but for the list."""

    commands = (
        Command("/dailypost"),
        Command("/dailyquote"),
        Command("/specials", more=True, timers=False),
        Command("/special", more=True, timers=False),
    )

    @classmethod
    def takes(cls, text: str) -> Command | None:
        """The admins' own specials too, by name."""
        return super().takes(text) or own_specials.command(text)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = context.message.text or ""
        words = text.split()
        if command.name == "/dailypost":
            await answer(context, daily_post, slow=True)
        elif command.name == "/dailyquote":
            await answer(context, daily_quote)
        elif command.name in ("/specials", "/special"):
            await answer(
                context,
                lambda: specials_answer(words, text),
                edits=words[1:2] in ([], ["list"]),
                styled=True,
            )
        elif parts := own_specials.specials.get(command.name):
            await answer(context, lambda: posts(parts), edits=False, slow=True)
