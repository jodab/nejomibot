"""/delivery: whether the bot's latest messages reached people's phones.

A phone confirms each message it gets with a delivery receipt, and each one
read with a read receipt, unless its read receipts are off. The bot keeps
them for what it sent in the last day, in memory, so a restart forgets them.
/delivery, in a direct chat, shows its delivery_messages latest messages,
wherever they went, newest first: when, where, how each starts, how many
got it, of those in the chat, and how many read it, as 📬 3/4 · 👀 2. One
nobody has confirmed yet shows ⏳, and once nobody has in 10 minutes, ⚠️,
which the log has as a warning too: Signal took it, but it may not have
arrived. At DEBUG, the log has how many each message reached in those 10
minutes.

signalbot drops receipts, so the bot hears them on a websocket of its own
(rest.received). signal-cli-rest-api up to 0.101, and its builds before
2026-10-13, may drop what reaches a websocket while it's busy with the
message before: of a burst of receipts some can be lost, and the counts can
come out low.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import aiohttp
from pydantic import BaseModel, Field, ValidationError
from signalbot import DataMessageContext, SignalBot

from . import access, rest
from .commands import Command, Handler, answer
from .config import get_settings
from .delete import nothing_since_start, sent_text
from .i18n import _
from .messages import (
    Sent,
    SentLog,
    describe,
    escape,
    log_failure,
    outbox,
    retry_delays,
    to_whom,
)

logger = logging.getLogger(__name__)

# By then a phone that's on has confirmed a message: one nobody confirmed is
# worth a word in the log
CHECK_AFTER = timedelta(minutes=10)
MINUTES = int(CHECK_AFTER.total_seconds() // 60)
# What only a receipt has in its JSON: the rest isn't parsed at all
RECEIPT = '"receiptMessage"'


class ReceiptMessage(BaseModel):
    is_read: bool = Field(default=False, alias="isRead")
    is_viewed: bool = Field(default=False, alias="isViewed")  # a photo, say
    timestamps: list[int] = []  # of the messages it's for


class Envelope(BaseModel):
    """A receipt, as signal-cli-rest-api passes it on: from whom, and for
    which of the bot's messages."""

    source_number: str | None = Field(default=None, alias="sourceNumber")
    source_uuid: str | None = Field(default=None, alias="sourceUuid")
    receipt_message: ReceiptMessage | None = Field(default=None, alias="receiptMessage")


class Received(BaseModel):
    envelope: Envelope


def receipt_in(data: str) -> Envelope | None:
    """The receipt that a message from signal-cli-rest-api is, if it's one."""
    if RECEIPT not in data:
        return None
    try:
        envelope = Received.model_validate_json(data).envelope
    except ValidationError:
        return None
    return envelope if envelope.receipt_message is not None else None


def confirm(log: SentLog, envelope: Envelope) -> None:
    """Note who confirmed the messages the receipt is for, and whether they
    read them."""
    receipt = envelope.receipt_message
    who = envelope.source_uuid or envelope.source_number
    if receipt is None or not who:
        return
    read = receipt.is_read or receipt.is_viewed
    for timestamp in receipt.timestamps:
        if sent := log.find(timestamp):
            sent.confirmed[who] = read or sent.confirmed.get(who, False)


def expected(bot: SignalBot, chat: str) -> int | None:
    """How many should confirm a message to the chat: a contact, or each of
    a group's members but the bot, which signal-cli-rest-api lists by its
    number; None for a group the bot isn't in."""
    if not access.is_group(chat):
        return 1
    group = next((g for g in bot.groups if g.id == chat and g.member), None)
    if group is None:
        return None
    return len(set(group.members) - {get_settings().account})


def status_text(sent: Sent, of: int | None, now: datetime) -> str:
    """E.g. '📬 3/4 · 👀 2': 3 of the 4 in the chat got it, and 2 read it; ⏳
    while nobody has confirmed it, ⚠️ once nobody has in CHECK_AFTER."""
    got = len(sent.confirmed)
    count = str(got) if of is None else f"{got}/{of}"
    if got or of == 0:
        read = sum(sent.confirmed.values())
        return f"📬 {count} · 👀 {read}" if read else f"📬 {count}"
    return f"{'⏳' if now - sent.at < CHECK_AFTER else '⚠️'} {count}"


class Receipts:
    """Hears the receipts for the bot's messages, and checks on each message
    CHECK_AFTER after it's sent."""

    def __init__(self) -> None:
        # Since when the bot hears the receipts, if it does: a message sent
        # before then may have had some it didn't hear
        self.since: datetime | None = None
        self.hearing: asyncio.Task[None] | None = None

    def start(self, bot: SignalBot) -> None:
        """Hear the receipts once signalbot is ready, as long as it runs."""

        def check_later(sent: Sent) -> None:
            loop = asyncio.get_running_loop()
            loop.call_later(CHECK_AFTER.total_seconds(), self.check, bot, sent)

        outbox.on_sent = check_later
        bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
            self.hear,
            args=[bot],
            id="delivery-receipts",
            misfire_grace_time=None,
            replace_existing=True,
        )

    async def hear(self, bot: SignalBot) -> None:
        """Listen in a task of its own, in signalbot's event loop: a job of the
        scheduler's that runs until the bot stops would be logged as failing
        when bot.shutdown() cancels it."""
        self.hearing = asyncio.create_task(self.listen(bot, outbox.sent))

    def heard_all(self, sent: Sent) -> bool:
        """Whether the bot has heard every receipt since the message was sent,
        as far as signal-cli-rest-api passed them on."""
        return self.since is not None and self.since <= sent.at

    def check(self, bot: SignalBot, sent: Sent) -> None:
        """Log how many confirmed the message: a warning if nobody did."""
        if not self.heard_all(sent):
            logger.debug(
                "Message %d: some receipts unheard, not checked", sent.timestamp
            )
            return
        of = expected(bot, sent.chat)
        got = len(sent.confirmed)
        if not got and of != 0:
            logger.warning(
                "Message %d %s: nobody's phone confirmed it in %d minutes. "
                "Signal took it, but it may not have arrived",
                sent.timestamp,
                to_whom(sent.chat),
                MINUTES,
            )
            return
        logger.debug(
            "Message %d to %s: %d of %s got it in %d minutes, %d read it",
            sent.timestamp,
            sent.chat,
            got,
            of,
            MINUTES,
            sum(sent.confirmed.values()),
        )

    async def listen(self, bot: SignalBot, log: SentLog) -> None:
        """Hear the receipts for as long as the bot runs, connecting again
        whenever the connection fails or ends: after 10 seconds, then less and
        less often, every 2 minutes at most."""
        await bot.wait_until_ready()
        said = ""  # what went wrong last, said once
        delays = retry_delays()
        while True:
            try:
                async with rest.received() as websocket:
                    self.since = datetime.now(UTC)
                    if said:
                        logger.info("Hearing receipts again")
                        said = ""
                    delays = retry_delays()
                    async for message in websocket:
                        if message.type is aiohttp.WSMsgType.TEXT and (
                            envelope := receipt_in(message.data)
                        ):
                            confirm(log, envelope)
                said = "the connection ended"
                logger.warning("Hearing receipts stopped: %s", said)
            except Exception as e:
                if (why := describe(e)) != said:
                    log_failure(logger, "Hearing receipts", e)
                    said = why
            finally:
                self.since = None
            await asyncio.sleep(next(delays).total_seconds())


receipts = Receipts()


async def delivery_text(bot: SignalBot, log: SentLog) -> str:
    """The bot's latest messages, wherever it sent them, newest first, and
    how many got and read each; or that it has sent none. Styled."""
    now = datetime.now(UTC)
    if not (latest := log.latest(get_settings().delivery_messages)):
        return escape(
            nothing_since_start(log.since, now)
            or _("No messages sent in the last 24 hours.")
        )
    names = await access.names(bot)
    lines = [
        f"{sent_text(sent, now, names)} · "
        + status_text(sent, expected(bot, sent.chat), now)
        for sent in latest
    ]
    notes = [
        _(
            "📬 delivered, of those in the chat · 👀 read · ⏳ none yet · "
            "⚠️ none within {minutes} minutes"
        ).format(minutes=MINUTES)
    ]
    if receipts.since is None:
        notes.insert(
            0,
            _(
                "⚠️ Delivery receipts are not being received at the moment: the "
                "counts may be behind."
            ),
        )
    title = _("Delivery of the bot's latest messages, newest first:")
    return f"📬 **{escape(title)}**\n" + escape("\n".join([*lines, "", *notes]))


class Delivery(Handler):
    commands = (Command("/delivery"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot = context.bot
        await answer(context, lambda: delivery_text(bot, outbox.sent), styled=True)
