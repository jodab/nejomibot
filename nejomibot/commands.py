"""Commands: how the bot takes them, by any of their names, and answers them.

A command has the name its handler gives it, in English, and aliases: other
names the bot comes with (ALIASES), and from the language (see i18n) and the
setting aliases. A message that starts with an alias is handled as if it
started with its command: /pic as /photo, /spådom startrek as /fortune
startrek.

Each handler is a Handler that lists its commands, saying of each whether
more may follow its name and whether timers and /run may run it. answer()
does what every command does: logs it, marks it read, shows the bot typing
for a slow one, and replies with what it says, or with what went wrong.
"""

import inspect
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from signalbot import (
    DataMessage,
    DataMessageContext,
    DataMessageHandler,
    EditMessage,
    SendMessage,
    TextMode,
)

from .config import get_settings
from .i18n import language
from .messages import collected, error_text, escape, log_failure, reply
from .receipts import mark_read, show_typing
from .styles import utf16_length

logger = logging.getLogger(__name__)

FIRST_WORD = re.compile(r"^\S+")
# Names the bot has had all along, in every language
ALIASES = {"/status": ["/test"], "/info": ["/time"], "/contacts": ["/safety"]}


def aliases() -> dict[str, str]:
    """Each alias, in lower case, and its command: the bot's own, the
    language's, then the settings', which win."""
    table: dict[str, str] = {}
    for command, names in [
        *ALIASES.items(),
        *language().commands.items(),
        *get_settings().aliases.items(),
    ]:
        for name in names:
            table[name.casefold()] = command
    return table


def canonical(text: str) -> str:
    """The text, an alias at its start replaced by its command."""
    if (word := FIRST_WORD.match(text)) and (
        command := aliases().get(word[0].casefold())
    ):
        return command + text[word.end() :]
    return text


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

    async def handle_data_message(self, context: DataMessageContext) -> None:
        context = resolved(context)
        if command := self.takes(context.message.text or ""):
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


def chat_kind(message: DataMessage) -> str:
    """Where a command came from, for the log, which says nothing of who."""
    if collected.get() is not None:
        return "for a timer, /run or a special"
    return "in a group" if message.is_group() else "in a direct chat"


type Reply = str | SendMessage
type Replies = Reply | Sequence[Reply] | None


async def answer(
    context: DataMessageContext,
    what: Callable[[], Replies | Awaitable[Replies]],
    *,
    edits: bool = True,
    slow: bool = False,
    styled: bool = False,
) -> None:
    """Answer the command with what() says, if anything, as text, styled if
    styled, or as the messages it makes; or with what went wrong. Its name
    and the kind of chat go in the log, the rest only at DEBUG.

    An EditMessage is a DataMessage, so an edit runs its command again; with
    edits false, as for commands that change something or post elsewhere,
    it's let be. A slow command shows the bot typing meanwhile."""
    message = context.message
    words = (message.text or "").split()
    name = words[0].lower() if words else "?"
    if not edits and isinstance(message, EditMessage):
        logger.info("Ignored an edited %s %s", name, chat_kind(message))
        return
    logger.info("Received %s %s", name, chat_kind(message))
    logger.debug(
        "From %s: %s", message.source_uuid or message.source_number, message.text
    )
    await mark_read(context)
    if slow:
        await show_typing(context)
    try:
        replies = what()
        if inspect.isawaitable(replies):
            replies = await replies
    except Exception as e:
        log_failure(logger, name, e)
        replies = escape(error_text(e)) if styled else error_text(e)
    if replies is None:
        return
    mode = TextMode.STYLED if styled else None
    for item in [replies] if isinstance(replies, str | SendMessage) else replies:
        if isinstance(item, str):
            item = SendMessage(text=item, text_mode=mode)
        await reply(context, item)
