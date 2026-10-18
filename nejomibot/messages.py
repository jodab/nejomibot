"""Sending messages, and the wording of errors posted to the chat.

Messages go out through signalbot. One that surely wasn't sent waits in the
outbox and is tried again, for up to send_retry_hours. Surely not sent:

- signal-cli-rest-api can't be reached: the request never got there.
- It answered with an error. It only does when signal-cli sent the message to
  nobody, e.g. without internet (400), or Signal rate-limits the bot (429), or
  the request itself is wrong (400). A send that reached some of a group
  counts as sent; signalbot logs who it didn't reach.

A timeout or a dropped connection may come after Signal got the message, and a
retry is a new message that would show up twice, so those aren't retried.

While Signal rate-limits the bot, waiting messages are tried every half hour,
as trying more often can keep the limit in place, until a message goes out.
A message that has waited half a minute is kept in data_dir/outbox, a file
each, until it's sent or dropped, and all of them are as the bot stops: the
bot sends them once it's started again. A short wait, as while
signal-cli-rest-api restarts, writes nothing.

Sent messages are remembered for as long as Signal can delete them, for
/delete.
"""

import asyncio
import contextlib
import functools
import itertools
import logging
import re
import time
from bisect import insort
from collections import Counter, defaultdict, deque
from collections.abc import Awaitable, Callable, Collection, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import NamedTuple

import aiohttp
from pydantic import BaseModel, ValidationError
from signalbot import (
    DataMessageContext,
    SendError,
    SendMessage,
    SignalAPIError,
    SignalBot,
    SignalBotError,
)

from .config import get_settings
from .files import write_privately
from .i18n import _, ngettext
from .rest import RestError

logger = logging.getLogger(__name__)

# Long enough for a photo upload; a send that takes longer may still arrive
SEND_TIMEOUT = 120  # seconds
# Waiting messages are tried again this soon, then twice as long after each
# try, up to RETRY_INTERVAL: signal-cli-rest-api restarts in seconds, while an
# internet outage can last for hours
FIRST_RETRY = timedelta(seconds=10)
RETRY_INTERVAL = timedelta(minutes=2)
# While Signal rate-limits the bot, as trying more often can keep the limit
RATE_LIMITED_RETRY = timedelta(minutes=30)
TOO_MANY_REQUESTS = 429
# A message waiting this long is kept on disk, so a restart doesn't lose it
KEEP_AFTER = timedelta(seconds=30)
# Signal only deletes a message for everyone this soon after it was sent
DELETABLE_FOR = timedelta(days=1)


def web_error(error: aiohttp.ClientError | TimeoutError) -> str:
    """A failed web request, by its status, or by its text where that has no
    URL; else by its kind. A URL can hold an API key or a phone number."""
    if isinstance(error, aiohttp.ClientResponseError) and error.status:
        return f"{error.status} {error.message}".strip()
    # Their text names the host at most
    if isinstance(
        error, aiohttp.ClientConnectorError | aiohttp.ServerDisconnectedError
    ):
        return str(error)
    return type(error).__name__


def describe(error: Exception) -> str:
    """What went wrong, in a few words. signalbot's errors keep it as their
    cause, without signal-cli-rest-api's own words."""
    cause = error.__cause__ if isinstance(error, SignalAPIError) else error
    if isinstance(error, SignalAPIError):
        if isinstance(cause, aiohttp.ClientResponseError):
            return _("signal-cli-rest-api answered {status} {reason}").format(
                status=cause.status, reason=cause.message
            )
        if isinstance(cause, aiohttp.ClientConnectorError):
            return _("signal-cli-rest-api can't be reached")
    if isinstance(cause, aiohttp.ClientError | TimeoutError):
        return web_error(cause)
    return str(error) or type(error).__name__


class ServiceError(Exception):
    """A service the bot asks failed, or said no, in words posted as they are."""


# Failures of what the bot relies on, rather than of the bot itself: a file or
# service that can't be had, or answers with an error
EXPECTED = (OSError, aiohttp.ClientError, SignalBotError, RestError, ServiceError)


def log_failure(log: logging.Logger, what: str, error: Exception) -> None:
    """Log a failure: an expected one in a line, else with where it happened."""
    if isinstance(error, EXPECTED):
        log.warning("%s failed: %s", what, describe(error))
    else:
        log.error("%s failed", what, exc_info=error)


def error_text(error: Exception | str) -> str:
    """An error as posted to the chat, so a failure is noticed, not silent."""
    if isinstance(error, Exception):
        error = describe(error)
    return _("Something went wrong: {error}").format(error=error)


def escape(text: str) -> str:
    """Text that shows as is in a styled message."""
    return re.sub(r"([*`|~])", r"\\\1", text)


def unreadable_text(lines: list[str]) -> str:
    """The lines of a file the bot can't read, as the commands that list the
    rest of the file show them."""
    return ngettext(
        "⚠️ The file has a line the bot can't read, and leaves as it is: {lines}",
        "⚠️ The file has {count} lines the bot can't read, and leaves as they "
        "are: {lines}",
        len(lines),
    ).format(count=len(lines), lines=" / ".join(lines))


class Outcome(Enum):
    SENT = auto()
    NOT_SENT = auto()  # surely not sent: it waits, to be tried again
    RATE_LIMITED = auto()  # not sent, as Signal rate-limits the bot: it waits
    GIVE_UP = auto()  # can't be sent, or may have arrived: not tried again

    @property
    def waits(self) -> bool:
        return self in (Outcome.NOT_SENT, Outcome.RATE_LIMITED)


class Posted(NamedTuple):
    outcome: Outcome
    timestamp: int | None = None  # of the message once sent, which deletes it


# Sends a message to a recipient
type Post = Callable[[str, SendMessage], Awaitable[Posted]]


def to_whom(recipient: str) -> str:
    """The kind of chat, for the log, which says nothing of who."""
    return "to a group" if recipient.startswith("group.") else "to a contact"


def outcome_of(error: SendError) -> Outcome:
    """Whether a failed send surely wasn't sent. signalbot keeps what went
    wrong as the error's cause, but not signal-cli-rest-api's answer."""
    cause = error.__cause__
    if isinstance(cause, aiohttp.ClientConnectorError):
        logger.warning("Not sent: %s", describe(error))
        return Outcome.NOT_SENT
    if isinstance(cause, aiohttp.ClientResponseError):
        if cause.status == TOO_MANY_REQUESTS:
            logger.warning(
                "Not sent: Signal rate-limits the bot. To lift the limit, run "
                "signal-account.sh rate-limit"
            )
            return Outcome.RATE_LIMITED
        logger.warning("Not sent, signal-cli-rest-api says %d", cause.status)
        return Outcome.NOT_SENT
    logger.warning("Send failed after submission, not retrying: %s", describe(error))
    return Outcome.GIVE_UP


async def post_message(bot: SignalBot, recipient: str, message: SendMessage) -> Posted:
    """Send one message through signalbot. Never raises."""
    try:
        async with asyncio.timeout(SEND_TIMEOUT):
            sent = await bot.messages.send(message, recipient)
    except SendError as e:
        return Posted(outcome_of(e))
    except TimeoutError:
        logger.warning("Send timed out, so it may have arrived; not retrying")
        return Posted(Outcome.GIVE_UP)
    except Exception:
        # Such as a recipient signalbot can't make out, or an odd answer
        logger.exception("Could not send a message %s", to_whom(recipient))
        return Posted(Outcome.GIVE_UP)
    return Posted(Outcome.SENT, sent.timestamp)


@dataclass(frozen=True, order=True)
class Sent:
    """A message the bot sent, as Signal knows it."""

    timestamp: int  # milliseconds since the epoch
    chat: str

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000, UTC)


class SentLog:
    """The bot's messages that Signal can still delete, oldest first. Only in
    memory, so a restart forgets them."""

    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._now = now
        self._sent: list[Sent] = []
        self.since = now()

    def add(self, sent: Sent) -> None:
        insort(self._sent, sent)
        self._forget_old()

    def pop(self, chats: Collection[str]) -> Sent | None:
        """The latest message to any of the chats, taken out of the log."""
        self._forget_old()
        for i in reversed(range(len(self._sent))):
            if self._sent[i].chat in chats:
                return self._sent.pop(i)
        return None

    def _forget_old(self) -> None:
        oldest = self._now() - DELETABLE_FOR
        while self._sent and self._sent[0].at < oldest:
            del self._sent[0]


class Kept(BaseModel):
    """A waiting message, as its file in data_dir/outbox has it."""

    recipient: str
    queued_at: datetime
    message: SendMessage


@dataclass(eq=False)
class Queued:
    recipient: str
    message: SendMessage
    queued_at: datetime
    path: Path  # where it's kept, once it is
    kept: bool = False
    gone: bool = False  # sent, or dropped

    def keep(self) -> None:
        """Write it to its file, unless it's there, or gone. Raises OSError."""
        if self.kept or self.gone:
            return
        self.path.parent.mkdir(mode=0o700, exist_ok=True)
        kept = Kept(
            recipient=self.recipient, queued_at=self.queued_at, message=self.message
        )
        write_privately(self.path, kept.model_dump_json(exclude_none=True))
        self.kept = True

    def forget(self) -> None:
        """It's gone: sent, or dropped. Its file goes too."""
        self.gone = True
        if self.kept:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as e:
                logger.error(
                    "Could not delete %s, so it'll be sent again: %r", self.path, e
                )


def retry_delays() -> Iterator[timedelta]:
    """How long to wait before each round of retries: 10 s, 20 s, 40 s...
    then every RETRY_INTERVAL."""
    delay = FIRST_RETRY
    while True:
        yield delay
        delay = min(delay * 2, RETRY_INTERVAL)


class Outbox:
    """Sends messages, keeping the ones that surely weren't sent to try again.

    Each recipient's messages go out in order: a new one waits behind any that
    are waiting, which are tried first. Messages older than send_retry_hours
    are dropped, and the recipient is told how many once sending works again.
    Sent ones are kept in the sent log, for /delete.
    """

    def __init__(
        self,
        post: Post | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._post = post
        self._now = now
        self._queues: defaultdict[str, deque[Queued]] = defaultdict(deque)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._dropped: Counter[str] = Counter()
        self._retrying: asyncio.Task[None] | None = None
        self._rate_limited = False
        self._wake: asyncio.Event | None = None  # wakes the retries early
        self._numbers = itertools.count()  # for the files' names
        self.sent = SentLog(now)

    def start(self, bot: SignalBot) -> None:
        """Send through the bot, from now on; first the messages kept from
        before, once it's ready."""
        self._post = functools.partial(post_message, bot)
        self.load()
        bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
            self.resume,
            args=[bot],
            id="outbox-resume",
            misfire_grace_time=None,
            replace_existing=True,
        )

    async def resume(self, bot: SignalBot) -> None:
        await bot.wait_until_ready()
        if self._queues:
            self._start_retrying()

    def __len__(self) -> int:
        return sum(len(queue) for queue in self._queues.values())

    def oldest(self) -> datetime | None:
        """When the message that has waited longest was queued, if any waits."""
        return min(
            (queue[0].queued_at for queue in self._queues.values() if queue),
            default=None,
        )

    async def send(self, recipient: str, message: SendMessage) -> Outcome:
        """Send now, or queue it if it surely wasn't sent. What became of it:
        if it waits, NOT_SENT or RATE_LIMITED. Never raises, once started.

        Messages waiting for the recipient go first, tried right away: a new
        one, like the answer to a command that just came in, often means
        Signal is back.
        """
        async with self._locks[recipient]:
            if recipient in self._queues:
                await self._flush(recipient)
            outcome = Outcome.NOT_SENT  # unless tried: it waits behind others
            if recipient not in self._queues:
                outcome = await self._try(recipient, message)
                if not outcome.waits:
                    return outcome
            self._queue(recipient, message)
            return outcome

    def _queue(self, recipient: str, message: SendMessage) -> None:
        at = self._now()
        name = f"{at:%Y%m%d-%H%M%S-%f}-{next(self._numbers)}.json"
        path = get_settings().outbox_dir / name
        queued = Queued(recipient, message, at, path)
        self._queues[recipient].append(queued)
        logger.info("Queued a message %s, %d waiting", to_whom(recipient), len(self))
        asyncio.get_running_loop().call_later(
            KEEP_AFTER.total_seconds(), self._keep, queued
        )
        self._start_retrying()

    def _keep(self, queued: Queued) -> None:
        """Keep the message on disk, if it still waits."""
        try:
            queued.keep()
        except OSError as e:
            logger.error(
                "Could not keep a waiting message, so a restart loses it: %r", e
            )

    def keep_all(self) -> None:
        """Keep every waiting message on disk, as the bot stops."""
        for queue in self._queues.values():
            for queued in queue:
                self._keep(queued)
        if self._queues:
            logger.info(
                "Kept %d waiting messages, to send after the restart", len(self)
            )

    def load(self) -> None:
        """Queue the messages kept on disk, as they were queued."""
        folder = get_settings().outbox_dir
        found: list[Queued] = []
        for path in sorted(folder.glob("*.json")):
            try:
                kept = Kept.model_validate_json(path.read_bytes())
            except (OSError, ValidationError) as e:
                logger.error("Left alone, as it can't be read: %s (%r)", path, e)
                continue
            found.append(
                Queued(kept.recipient, kept.message, kept.queued_at, path, kept=True)
            )
        for queued in sorted(found, key=lambda queued: queued.queued_at):
            self._queues[queued.recipient].append(queued)
        if found:
            logger.info("%d messages waiting to be sent, from before", len(found))

    async def flush(self) -> None:
        """Try the waiting messages again, oldest first, and drop expired ones."""
        for recipient in list(self._queues):
            async with self._locks[recipient]:
                await self._flush(recipient)

    async def _flush(self, recipient: str) -> None:
        queue = self._queues[recipient]
        self._expire(recipient, queue)
        while queue:
            first = queue[0]
            if (await self._try(recipient, first.message, first.queued_at)).waits:
                return
            queue.popleft().forget()
        del self._queues[recipient]

    def _expire(self, recipient: str, queue: deque[Queued]) -> None:
        max_age = timedelta(hours=get_settings().send_retry_hours)
        while queue and self._now() - queue[0].queued_at > max_age:
            queue.popleft().forget()
            self._dropped[recipient] += 1
            logger.warning(
                "Dropped a message %s, not sent in %s", to_whom(recipient), max_age
            )

    async def _try(
        self, recipient: str, message: SendMessage, queued_at: datetime | None = None
    ) -> Outcome:
        if self._post is None:
            raise RuntimeError("The outbox isn't started")
        if queued_at is not None:
            message = delayed(message, queued_at)
        outcome, timestamp = await self._post(recipient, message)
        if outcome is Outcome.RATE_LIMITED:
            self._rate_limited = True
        if outcome is not Outcome.SENT:
            return outcome
        logger.debug("Sent a message to %s", recipient)
        if self._rate_limited:
            # The limit is lifted: the others needn't wait their half hour
            self._rate_limited = False
            if self._wake is not None:
                self._wake.set()
        if timestamp is not None:
            self.sent.add(Sent(timestamp, recipient))
        if dropped := self._dropped.pop(recipient, 0):
            notice = SendMessage(text=dropped_text(dropped))
            if await self._try(recipient, notice) is not Outcome.SENT:
                self._dropped[recipient] += dropped
        return outcome

    def _start_retrying(self) -> None:
        if self._retrying is None or self._retrying.done():
            self._retrying = asyncio.create_task(self._retry_loop())

    async def _retry_loop(self) -> None:
        delays = retry_delays()
        self._wake = asyncio.Event()
        while self._queues:
            delay = RATE_LIMITED_RETRY if self._rate_limited else next(delays)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(delay.total_seconds()):
                    await self._wake.wait()
            self._wake.clear()
            try:
                await self.flush()
            except Exception:
                logger.exception("Retrying queued messages failed")
        # No await between the last check and this, so nothing queued since
        self._retrying = self._wake = None


def delayed(message: SendMessage, queued_at: datetime) -> SendMessage:
    """The message with a note that it's late. Added last, so that mention
    positions in the text still hold."""
    at = queued_at.astimezone(get_settings().tz)
    note = _("⏳ Late: it should have been sent at {time}").format(time=f"{at:%H:%M}")
    text = f"{message.text}\n\n{note}" if message.text else note
    return message.model_copy(update={"text": text})


def dropped_text(count: int) -> str:
    hours = get_settings().send_retry_hours
    return error_text(
        ngettext(
            "{count} message couldn't be sent in {hours} hours, and was dropped",
            "{count} messages couldn't be sent in {hours} hours, and were dropped",
            count,
        ).format(count=count, hours=f"{hours:g}")
    )


outbox = Outbox()


def chat_of(bot: SignalBot, recipient: str) -> str:
    """The recipient as the outbox knows it: a group by its group.… ID."""
    return bot.groups.resolve(recipient) or recipient


async def send(bot: SignalBot, recipient: str, message: SendMessage) -> Outcome:
    """Send to a contact or group, retrying while Signal can't be reached:
    what became of it. Never raises."""
    return await outbox.send(chat_of(bot, recipient), message)


def arrival_delay(context: DataMessageContext) -> float:
    """Seconds the command took to reach the bot. Its timestamp is from the
    sender's clock, so this includes any difference in clocks."""
    return time.time() - context.message.timestamp / 1000


# While a timer, /run or a special runs a command, its answers are collected
# here, for it to post, rather than sent to whoever "sent" the command
collected: ContextVar[list[SendMessage] | None] = ContextVar("collected", default=None)


async def reply(context: DataMessageContext, message: SendMessage) -> None:
    """Send to the chat the command came from. Never raises."""
    if (answers := collected.get()) is not None:
        answers.append(message)
        return
    await send(context.bot, context.message.source_or_group_id(), message)
