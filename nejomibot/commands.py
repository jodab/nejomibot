"""Commands: how the bot takes them, by any of their names, and answers them.

A command has the name its handler gives it, in English, and aliases: other
names the bot comes with (ALIASES), and from every language (see i18n) and
the setting aliases. A message that starts with an alias is handled as if it
started with its command: /pic as /photo, /spådom startrek as /fortune
startrek. So are every language's words for what follows a command, its
subcommands: /lista lägg till mjölk as /list add mjölk, /spådom alla as
/fortune all. A handler may have shortcuts too, aliases the admins give, for
its command and words after it: an album's, as alice 2017 for /photo Alice
2017, or a special's, as /gm for /morning. The bot answers in the chat's
language (i18n.speaking()).

Each handler is a Handler that lists its commands, saying of each whether
more may follow its name and whether timers and /run may run it. answer()
does what every command does: logs it, marks it read, shows the bot typing
for a slow one, and replies with what it says, or with what went wrong.

Signal lets a message be edited for a day, and the bot gets the edit as a
message of its own, naming the one it edits. What answer() does with it
depends on the command (Edits): one that shows something, or sets a value,
runs again; one that adds or removes something first has what the message
did undone, so the edit takes its place, as the command said how with
undo_with(); one whose post or deletion can't be undone isn't run.
"""

import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar

from signalbot import (
    DataMessage,
    DataMessageContext,
    DataMessageHandler,
    EditMessage,
    SendMessage,
    TextMode,
)

from .config import DOT, get_settings, slashed
from .i18n import _, every_language, prefixed, speaking, speaking_now
from .messages import collected, error_text, escape, language_here, log_failure, reply
from .receipts import mark_read, show_typing
from .styles import utf16_length

logger = logging.getLogger(__name__)

FIRST_WORD = re.compile(r"^\S+")
COMMAND_AND_SPACE = re.compile(r"^(\S+)\s+")
# Where a command starts in a text, as after /timer add's time: a word that
# starts with a /, or a . (slashed)
COMMAND_START = re.compile(rf"(?:^|\s)(?:/|{DOT.pattern})")
# Names the bot has had all along, in every language
ALIASES = {
    "/status": ["/test"],
    "/info": ["/time"],
    "/contacts": ["/safety"],
    "/today": ["/day"],  # its own command till /today lost the weather
}


def aliases(*, shortcuts: bool = True) -> dict[str, str]:
    """Each alias, in lower case, and what it stands for: the handlers'
    shortcuts, which come and go as the bot runs, unless not wanted; the
    bot's own, every language's, then the settings', each winning over
    those before."""
    table: dict[str, str] = {}
    if shortcuts:
        for handler in handlers():
            table.update(handler.shortcuts())
    for command, names in [
        *ALIASES.items(),
        *(item for lang in every_language() for item in lang.commands.items()),
        *get_settings().aliases.items(),
    ]:
        for name in names:
            table[name.casefold()] = command
    return table


def canonical(text: str) -> str:
    """The text, its command with a / (slashed), an alias at its start
    replaced by its command, and the language's words for a subcommand after
    it by the English ones."""
    text = slashed(text)
    if (word := FIRST_WORD.match(text)) and (
        command := aliases().get(word[0].casefold())
    ):
        text = command + text[word.end() :]
    return in_english(text)


def in_english(text: str) -> str:
    """The text, a language's words for a subcommand right after its command
    replaced by the English, as the command takes it."""
    if not (head := COMMAND_AND_SPACE.match(text)):
        return text
    rest = text[head.end() :]
    for english, phrase in subcommand_words(head[1].lower()):
        pattern = r"\s+".join(map(re.escape, phrase.split())) + r"(?=\s|$)"
        if found := re.match(pattern, rest, re.IGNORECASE):
            return text[: head.end()] + english + rest[found.end() :]
    return text


def subcommand_words(command: str) -> list[tuple[str, str]]:
    """Every language's words for the command's subcommands, the longest
    first, each with the English it means."""
    words: dict[str, list[str]] = {}
    for lang in every_language():
        for word, phrases in lang.words.items():
            words.setdefault(word, []).extend(phrases)
    if not words:
        return []
    english: set[str] = set()
    for handler in handlers():
        for each in handler.commands:
            name, _space, second = each.name.partition(" ")
            if name == command:
                english.update(each.subcommands, [second] if second else [])
    found = [(word, phrase) for word in english for phrase in words.get(word, [])]
    return sorted(found, key=lambda each: -len(each[1]))


def resolved(context: DataMessageContext) -> DataMessageContext:
    """The context, with the message's alias replaced by its command, and its
    text styles moved with the text after it."""
    text = context.message.text
    if text is None or (command_text := canonical(text)) == text:
        return context
    shift = utf16_length(command_text) - utf16_length(text)
    styles = context.message.text_styles
    if styles:
        styles = [s.model_copy(update={"start": s.start + shift}) for s in styles]
    message = context.message.model_copy(
        update={"text": command_text, "text_styles": styles}
    )
    return DataMessageContext(context.bot, message)


def argument(text: str | None) -> str:
    """What follows the command, its spaces and line breaks made single."""
    return " ".join((text or "").split()[1:])


def numbers_in(text: str) -> list[int] | None:
    """The numbers in text such as 2,5,11 or 2 5 11, as a list numbers them,
    each once; None if it has anything else, or a number too long for a
    list's."""
    words = [word.lstrip("#") for word in re.split(r"[\s,]+", text) if word]
    if not words or not all(word.isdecimal() and len(word) <= 4 for word in words):
        return None
    return list(dict.fromkeys(map(int, words)))


@dataclass(frozen=True)
class Command:
    """A command, as its handler takes it."""

    name: str  # in English, as /help shows it
    more: bool = False  # more may follow the name, as in /fortune startrek
    timers: bool = True  # timers and /run may run it
    # What may follow it to say what it does, in English, as add in /timer
    # add: the language's words for these are taken too (in_english)
    subcommands: tuple[str, ...] = ()

    def takes(self, text: str) -> bool:
        """Whether the text is the command, by its name, in any case: the
        whole text, or its start, if more may follow."""
        if self.more:
            return bool(re.match(rf"{re.escape(self.name)}(\s|$)", text, re.IGNORECASE))
        return text.lower() == self.name.lower()


class Handler(DataMessageHandler):
    """A handler of commands: a message that is one of them, once its alias
    is replaced, goes to handle()."""

    commands: ClassVar[tuple[Command, ...]] = ()

    @classmethod
    def takes(cls, text: str) -> Command | None:
        return next((command for command in cls.commands if command.takes(text)), None)

    @classmethod
    def shortcuts(cls) -> dict[str, str]:
        """Aliases the admins give it, in lower case, each with the command
        and words it stands for, as an album's (photos.py)."""
        return {}

    async def handle_data_message(self, context: DataMessageContext) -> None:
        context = resolved(context)
        if command := self.takes(context.message.text or ""):
            # In the chat's language, but for a timer's or /run's, which
            # speaks that of the chats it posts to
            with speaking(speaking_now.get() or language_here(context)):
                await self.handle(context, command)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        raise NotImplementedError


def handlers() -> list[type[Handler]]:
    """The bot's handlers: those Python has read, as bot.py sees to, but for
    stand-ins the tests make."""
    return [
        h for h in Handler.__subclasses__() if h.__module__.startswith("nejomibot.")
    ]


def known(text: str) -> Command | None:
    """The command the text is, if any: one a handler lists, or one it takes
    besides, as the admins' own specials (specials.py)."""
    return next((command for h in handlers() if (command := h.takes(text))), None)


def built_in(text: str) -> Command | None:
    """The command the text is, if any, of those the handlers list: the ones
    the bot comes with, whatever the admins have added."""
    return next((c for h in handlers() for c in h.commands if c.takes(text)), None)


def shortcut_clash(shortcut: str, stands_for: str) -> str | None:
    """Why the shortcut can't be another name for stands_for, a command and
    the words after it, if it can't: a name the bot answers to already would
    hide one of the two. One that stands for it already may stay."""
    if "|" in shortcut or ";" in shortcut:
        return _("A shortcut can't have a | or a ;.")
    folded, shown = shortcut.casefold(), prefixed(shortcut)
    if any(
        folded == each.casefold() for x in get_settings().aliases.values() for each in x
    ):
        return _("{name} is an alias in the config: take it out there first.").format(
            name=shown
        )
    if known(shortcut) or folded in aliases(shortcuts=False):
        return _("{name} is a command already.").format(name=shown)
    for handler in handlers():
        other = handler.shortcuts().get(folded)
        if other is not None and other.casefold() != stands_for.casefold():
            return _("{name} is a shortcut for {album} already.").format(
                name=shown, album=prefixed(other)
            )
    return None


def chat_kind(message: DataMessage) -> str:
    """Where a command came from, for the log, which says nothing of who."""
    if collected.get() is not None:
        return "for a timer, /run or a special"
    return "in a group" if message.is_group() else "in a direct chat"


type Reply = str | SendMessage
type Replies = Reply | Sequence[Reply] | None


class Edits(Enum):
    """What an edit of a command's message does."""

    RUN_AGAIN = auto()  # it shows something, or sets a value: run it again
    REPLACE = auto()  # it adds or removes something: undo that, then run
    NOT_RUN = auto()  # a post or deletion can't be undone: say so
    IGNORE = auto()  # as NOT_RUN, quietly, for /delete, whose note would go next


# What the commands that add or remove something did, by the message, so an
# edit of it can undo that first. An edit names the message it edits by when
# it was sent: Signal Desktop names the latest edit, others the first message,
# so what an edit did is kept under both. For a day, as Signal lets a message
# be edited for a day, and only in memory: after a restart, an edit of a
# message from before isn't run, as the bot can't tell what that did.
EDITABLE_FOR = 24 * 60 * 60  # seconds
MAX_DONE = 500
STARTED = time.time()
# A message stamped this soon after the start may be from before it, as the
# sender's clock may be ahead of the bot's
CLOCKS_DIFFER = 120  # seconds

type Undo = Callable[[], object]  # may return an awaitable, which is awaited


@dataclass
class Done:
    """What a message's command did, to undo for an edit of it."""

    at: float  # when, by time.monotonic
    undos: list[Undo] = field(default_factory=list[Undo])
    final: str = ""  # why it can't be undone, if it can't


done: dict[tuple[str, int], Done] = {}
doing: ContextVar[Done | None] = ContextVar("doing", default=None)


def undo_with(undo: Undo) -> None:
    """For a command that adds or removes something: how to undo what it
    just did, if an edit of its message comes. The last is undone first."""
    if (now := doing.get()) is not None:
        now.undos.append(undo)


def cannot_undo(why: str) -> None:
    """For a command that did what can't be undone: an edit of its message
    says why, and isn't run."""
    if (now := doing.get()) is not None:
        now.final = why


def message_keys(message: DataMessage) -> set[tuple[str, int]]:
    """Who sent the message, and when, as Signal knows it; an edit also by
    the message it edits, which the next edit may name instead."""
    sender = message.source_uuid or message.source_number or ""
    keys = {(sender, message.timestamp)}
    if isinstance(message, EditMessage):
        keys.add((sender, message.target_sent_timestamp))
    return keys


def remember(keys: set[tuple[str, int]], did: Done) -> None:
    """Keep what a command did, for as long as its message can be edited, and
    no more than MAX_DONE names' worth."""
    now = time.monotonic()
    for old in [k for k, each in done.items() if now - each.at > EDITABLE_FOR]:
        del done[old]
    for key in sorted(keys):
        done.pop(key, None)  # last, as the newest
        done[key] = did
    while len(done) > MAX_DONE:
        del done[next(iter(done))]


async def undo_first(message: EditMessage) -> str | None:
    """Undo what the message the edit edits did, so the edit takes its place;
    or why it can't be, as when the bot can't tell what that did."""
    sender = message.source_uuid or message.source_number or ""
    when = message.target_sent_timestamp
    if (first := done.get((sender, when))) is None:
        if when / 1000 < STARTED + CLOCKS_DIFFER:
            return _(
                "✏️ That edit isn't run: the bot has started again since the "
                "message it edits, so it can't tell what that did. Send it as a "
                "new message instead."
            )
        return None  # the bot has had it, and it changed nothing
    if first.final:
        return first.final
    try:
        for undo in reversed(first.undos):
            if inspect.isawaitable(result := undo()):
                await result
    except Exception:
        first.final = _(
            "✏️ That edit isn't run: undoing what the message it edits did "
            "failed. Send it as a new message instead."
        )
        raise
    # Undone: forgotten by every name, so nothing undoes it again
    for key in [key for key, each in done.items() if each is first]:
        del done[key]
    return None


async def answer(
    context: DataMessageContext,
    what: Callable[[], Replies | Awaitable[Replies]],
    *,
    edits: Edits = Edits.RUN_AGAIN,
    slow: bool = False,
    styled: bool = False,
) -> None:
    """Answer the command with what() says, if anything, as text, styled if
    styled, or as the messages it makes; or with what went wrong. Its name
    and the kind of chat go in the log, the rest only at DEBUG.

    An EditMessage is a DataMessage: what an edit does, edits says. A slow
    command shows the bot typing meanwhile."""
    message = context.message
    words = (message.text or "").split()
    name = words[0].lower() if words else "?"
    edited = isinstance(message, EditMessage)
    if edited and edits in (Edits.NOT_RUN, Edits.IGNORE):
        logger.info("Ignored an edited %s %s", name, chat_kind(message))
        if edits is Edits.NOT_RUN:
            note = _(
                "✏️ An edit of {command} isn't run, as what it did can't be "
                "undone. Send it as a new message instead."
            ).format(command=prefixed(name))
            await reply(context, SendMessage(text=note))
        return
    logger.info("Received %s %s", name, chat_kind(message))
    logger.debug(
        "From %s: %s", message.source_uuid or message.source_number, message.text
    )
    await mark_read(context)
    if slow:
        await show_typing(context)
    # What it does is kept for an edit, but for a timer, /run or a special's
    keep = edits is Edits.REPLACE and collected.get() is None
    did = Done(time.monotonic()) if keep else None
    ran = False
    try:
        why = await undo_first(message) if did and edited else None
        if why:
            # So an edit of this edit is refused too, whichever it names
            remember(message_keys(message), Done(time.monotonic(), final=why))
            replies = escape(why) if styled else why
        else:
            ran = True
            token = doing.set(did)
            try:
                replies = what()
                if inspect.isawaitable(replies):
                    replies = await replies
            finally:
                doing.reset(token)
    except Exception as e:
        log_failure(logger, name, e)
        replies = escape(error_text(e)) if styled else error_text(e)
    # What it did before it failed, too
    if did is not None and ran:
        remember(message_keys(message), did)
    if replies is None:
        return
    mode = TextMode.STYLED if styled else None
    for item in [replies] if isinstance(replies, str | SendMessage) else replies:
        if isinstance(item, str):
            item = SendMessage(text=item, text_mode=mode)
        await reply(context, item)
