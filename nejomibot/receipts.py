"""Read receipts and the typing indicator, so the sender sees that the bot has
read their command and is working on it.

Both are niceties: they never raise and give up after a few seconds, so they
can't hold up or stop the answer. Each is a message to Signal's servers, so
neither is sent while Signal rate-limits the bot: it would only meet the
limit.
"""

import asyncio
import logging

from signalbot import DataMessageContext, ReceiptType

from .messages import collected, describe, outbox

logger = logging.getLogger(__name__)

TIMEOUT = 5  # seconds


async def mark_read(context: DataMessageContext) -> None:
    """Send a read receipt for the message. Never raises. Not for a timer's
    command: nobody sent it."""
    if collected.get() is not None or outbox.rate_limited:
        return
    # signalbot sends no receipts for group messages, but a receipt goes to
    # the sender either way, so it's sent as for their direct message
    message = context.message.model_copy(update={"group_info": None})
    try:
        async with asyncio.timeout(TIMEOUT):
            await context.bot.receipts.send(message, ReceiptType.READ)
    except Exception as e:
        logger.warning("Could not send read receipt: %s", describe(e))


async def show_typing(context: DataMessageContext) -> None:
    """Show the bot as typing in the chat. Never raises. Not for a timer's
    command: there's nobody to see it."""
    if collected.get() is not None or outbox.rate_limited:
        return
    try:
        async with asyncio.timeout(TIMEOUT):
            await context.start_typing()
    except Exception as e:
        logger.warning("Could not show typing: %s", describe(e))
