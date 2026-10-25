"""Read receipts and the typing indicator, so the sender sees that the bot has
read their command and is working on it.

Both are niceties: they never raise and give up after a few seconds, so they
can't hold up or stop the answer. Each is a message to Signal's servers, so
neither is sent while Signal rate-limits the bot: it would only meet the
limit.

Signal's apps show the bot typing for 15 seconds after each typing message,
and send theirs every 10 while someone types: so does the bot while a
command runs (Typing), for two minutes at most, so a stuck command can't run
the bot into Signal's limits.
"""

import asyncio
import logging

from signalbot import DataMessageContext, ReceiptType

from .messages import collected, describe, outbox

logger = logging.getLogger(__name__)

TIMEOUT = 5  # seconds
TYPING_AFTER = 1.0  # seconds a command runs before the bot shows it typing
TYPING_EVERY = 10.0  # seconds between typing messages while it still runs
TYPING_FOR = 120.0  # seconds at most


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


async def stop_typing(context: DataMessageContext) -> None:
    """Stop showing the bot as typing in the chat. Never raises."""
    if collected.get() is not None or outbox.rate_limited:
        return
    try:
        async with asyncio.timeout(TIMEOUT):
            await context.stop_typing()
    except Exception as e:
        logger.warning("Could not stop typing: %s", describe(e))


class Typing:
    """The bot typing while a command runs: from the start for a slow one,
    else once it has run for TYPING_AFTER; then again every TYPING_EVERY,
    until stop(), or TYPING_FOR has passed. Not for a timer's command."""

    def __init__(self, context: DataMessageContext, *, at_once: bool) -> None:
        self.context = context
        self.shown = False
        self.sending: asyncio.Task[None] | None = None
        delay = 0 if at_once else TYPING_AFTER
        self.task = (
            asyncio.create_task(self.keep(delay)) if collected.get() is None else None
        )

    async def keep(self, delay: float) -> None:
        await asyncio.sleep(delay)
        clock = asyncio.get_running_loop()
        until = clock.time() + TYPING_FOR
        while clock.time() < until:
            self.sending = asyncio.create_task(show_typing(self.context))
            self.shown = True
            # A stop waits for it, so it can't come after the answer
            await asyncio.shield(self.sending)
            await asyncio.sleep(TYPING_EVERY)

    async def stop(self, *, answered: bool) -> None:
        """No more typing messages, once one on its way has gone; without an
        answer, which ends the indicator, it's stopped."""
        if self.task is None:
            return
        self.task.cancel()
        if self.sending is not None:
            await self.sending
        if self.shown and not answered:
            await stop_typing(self.context)

    def cancel(self) -> None:
        """As the command is cancelled, as when the bot stops."""
        for task in (self.task, self.sending):
            if task is not None:
                task.cancel()
