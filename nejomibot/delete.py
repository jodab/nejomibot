"""/delete: delete the bot's latest message in the chat, for everyone. Sent
again, it deletes the one before, and so on. Only for the admins, in groups
as well as direct chats.

Signal only deletes messages for everyone within a day of sending them, and
the bot only knows what it has sent since it started.
"""

import logging
from datetime import UTC, datetime

from signalbot import DataMessageContext, SentMessage, SignalBot

from .access import is_admin
from .commands import Command, Handler, answer
from .config import get_settings
from .i18n import _
from .messages import (
    DELETABLE_FOR,
    Sent,
    SentLog,
    chat_of,
    error_text,
    log_failure,
    outbox,
)

logger = logging.getLogger(__name__)


def chats_of(context: DataMessageContext) -> set[str]:
    """The chat the command came from, as the outbox knows it. A direct chat
    may be known by phone number or by ID."""
    message = context.message
    if message.is_group():
        return {chat_of(context.bot, message.source_or_group_id())}
    return {who for who in (message.source_uuid, message.source_number) if who}


async def remote_delete(bot: SignalBot, sent: Sent) -> None:
    """Delete the message for everyone in its chat."""
    message = SentMessage(recipient=sent.chat, timestamp=sent.timestamp)
    await bot.messages.remote_delete(message)


def nothing_text(since: datetime, now: datetime) -> str:
    if now - since < DELETABLE_FOR:
        started = since.astimezone(get_settings().tz)
        return _(
            "Nothing left to delete here since the bot started, at {time}."
        ).format(time=f"{started:%Y-%m-%d %H:%M}")
    return _(
        "Nothing left to delete here from the last day: Signal only deletes "
        "messages for everyone within a day."
    )


async def delete_latest(bot: SignalBot, log: SentLog, chats: set[str]) -> str | None:
    """Delete the bot's latest message in the chat. None once it's deleted,
    else what went wrong."""
    if not (sent := log.pop(chats)):
        return nothing_text(log.since, datetime.now(UTC))
    try:
        await remote_delete(bot, sent)
    except Exception as e:
        log_failure(logger, f"Deleting message {sent.timestamp}", e)
        log.add(sent)  # still there, for next time
        return error_text(e)
    logger.info("Deleted message %d", sent.timestamp)
    return None


class Delete(Handler):
    commands = (Command("/delete"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        # signalbot only checks who sent it in direct chats
        if not is_admin(message):
            logger.info("Ignored /delete from someone not an admin")
            return
        # Deleted is reply enough: anything posted would be the next to go.
        # It deletes, so only a new message does.
        await answer(
            context,
            lambda: delete_latest(context.bot, outbox.sent, chats_of(context)),
            edits=False,
        )
