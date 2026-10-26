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

While Signal rate-limits the bot (signal-cli-rest-api says 429: Signal wants
a captcha solved first), nothing is sent at once, as each try would meet the
limit, and many could keep it in place: new messages wait behind the others.
The one that has waited longest is tried alone, after two minutes, then
twice as long after each try, rate_limit_retry_minutes apart at most; and at
once, a minute after the last try at the soonest, when an admin sends a
command, as they may have just lifted the limit. Once it goes out, the limit
is lifted, and the rest follow.

A message that has waited half a minute is kept in data_dir/outbox, a file
each, until it's sent or dropped, and all of them are as the bot stops: the
bot sends them once it's started again. A short wait, as while
signal-cli-rest-api restarts, writes nothing.

Sent messages are remembered for as long as Signal can delete them, with
how they start, for /delete, and whose phones confirmed them, for /delivery.
"""

import asyncio
import contextlib
import functools
import itertools
import logging
import random
import time
from bisect import bisect_left, insort
from collections import Counter, defaultdict, deque
from collections.abc import Awaitable, Callable, Collection, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import NamedTuple, Self

import aiohttp
from pydantic import BaseModel, Field, ValidationError
from signalbot import (
    DataMessageContext,
    SendError,
    SendMessage,
    SignalAPIError,
    SignalBot,
    SignalBotError,
    TextMode,
)

from .config import get_settings
from .files import write_privately
from .i18n import _, chat_language, ngettext, speaking
from .rest import RestError
from .styles import PLACEHOLDER, escape, mentioned

logger = logging.getLogger(__name__)

# Long enough for a photo upload; a send that takes longer may still arrive
SEND_TIMEOUT = 120  # seconds
# Waiting messages are tried again this soon, then twice as long after each
# try, up to RETRY_INTERVAL: signal-cli-rest-api restarts in seconds, while an
# internet outage can last for hours
FIRST_RETRY = timedelta(seconds=10)
RETRY_INTERVAL = timedelta(minutes=2)
# While Signal rate-limits the bot, one is tried this soon, then twice as
# long after each try, up to rate_limit_retry_minutes; and as an admin sends
# a command, this long after the last try at the soonest
RATE_LIMITED_FIRST = timedelta(minutes=2)
NUDGE_AFTER = timedelta(minutes=1)
TOO_MANY_REQUESTS = 429
# A message waiting this long is kept on disk, so a restart doesn't lose it
KEEP_AFTER = timedelta(seconds=30)
# Signal only deletes a message for everyone this soon after it was sent
DELETABLE_FOR = timedelta(days=1)
# Characters of a message's start that a list of messages shows, at most
SHORT = 20


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
            return _("signal-cli-rest-api returned {status} {reason}").format(
                status=cause.status, reason=cause.message
            )
        if isinstance(cause, aiohttp.ClientConnectorError):
            return _("signal-cli-rest-api is unreachable")
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


def unkept_formatting_text() -> str:
    """Why a message's formatting can't be kept: marks can't say it."""
    return _(
        "That formatting can't be kept: bold and italic can't meet "
        "inside a word, nor a style start or end right by a \\ or *."
    )


def short(text: str) -> str:
    """The text's first line, cut short, for a list of messages."""
    line = text.strip().partition("\n")[0]
    return line if len(line) <= SHORT else line[: SHORT - 1].rstrip() + "…"


def unreadable_text(lines: list[str]) -> str:
    """The lines of a file the bot can't read, as the commands that list the
    rest of the file show them."""
    return ngettext(
        "⚠️ The file has {count} unreadable line, which is ignored and left "
        "unchanged: {lines}",
        "⚠️ The file has {count} unreadable lines, which are ignored and left "
        "unchanged: {lines}",
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
                "nejomibot-account rate-limit"
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
    """A message the bot sent, as Signal knows it, how it starts, and who has
    confirmed it."""

    timestamp: int  # milliseconds since the epoch
    chat: str
    start: str = field(default="", compare=False)  # its text's first line
    styled: bool = field(default=False, compare=False)  # the start is in marks
    photo: bool = field(default=False, compare=False)
    # Those whose phones confirmed it with a receipt, by Signal ID, and
    # whether they read it (delivery.py)
    confirmed: dict[str, bool] = field(default_factory=dict[str, bool], compare=False)

    @classmethod
    def of(cls, timestamp: int, chat: str, message: SendMessage) -> Self:
        # A mention shows as @, without the name
        text = (message.text or "").replace(PLACEHOLDER, "@").strip()
        return cls(
            timestamp,
            chat,
            text.partition("\n")[0],
            message.text_mode == TextMode.STYLED,
            bool(message.base64_attachments),
        )

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

    def latest(self, count: int) -> list[Sent]:
        """The latest messages, to any chat, newest first."""
        self._forget_old()
        return self._sent[-count:][::-1]

    def find(self, timestamp: int) -> Sent | None:
        """The message sent at the timestamp, if it's in the log."""
        i = bisect_left(self._sent, timestamp, key=lambda sent: sent.timestamp)
        if i < len(self._sent) and self._sent[i].timestamp == timestamp:
            return self._sent[i]
        return None

    def take(self, sent: Sent) -> bool:
        """Take the message out of the log, if it's still there."""
        self._forget_old()
        if sent not in self._sent:
            return False
        self._sent.remove(sent)
        return True

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


def rate_limited_delays() -> Iterator[timedelta]:
    """How long to wait before each try while Signal rate-limits the bot:
    2 min, 4 min, 8 min... then every rate_limit_retry_minutes."""
    longest = timedelta(minutes=get_settings().rate_limit_retry_minutes)
    delay = RATE_LIMITED_FIRST
    while True:
        yield min(delay, longest)
        delay = min(delay * 2, longest)


class Outbox:
    """Sends messages, keeping the ones that surely weren't sent to try again.

    Each recipient's messages go out in order: a new one waits behind any that
    are waiting, which are tried first. While Signal rate-limits the bot, all
    wait, and one at a time is tried (probe()). Messages older than
    send_retry_hours are dropped, and the recipient is told how many once
    sending works again. Sent ones are kept in the sent log, for /delete.
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
        # Sends given up and waiting messages dropped since the start, which
        # the health checks report (health.py)
        self.given_up = 0
        self.discarded = 0
        self._retrying: asyncio.Task[None] | None = None
        self._rate_limited = False
        # When a try last met Signal's rate limit, by time.monotonic
        self._limited_at: float | None = None
        self._wake: asyncio.Event | None = None  # wakes the retries early
        self._numbers = itertools.count()  # for the files' names
        self.sent = SentLog(now)
        # Called as Signal starts rate-limiting the bot (notices.py)
        self.on_rate_limited: Callable[[], None] | None = None
        # Called with each message sent, once it's in the sent log
        # (delivery.py)
        self.on_sent: Callable[[Sent], None] | None = None

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

    @property
    def rate_limited(self) -> bool:
        """Whether Signal rate-limits the bot, as far as the latest sends tell."""
        return self._rate_limited

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
        Signal is back. While Signal rate-limits the bot, it isn't tried: it
        waits behind the others, as a try would only meet the limit.
        """
        async with self._locks[recipient]:
            if not self._rate_limited and recipient in self._queues:
                await self._flush(recipient)
            if self._rate_limited:
                self._queue(recipient, message)
                return Outcome.RATE_LIMITED
            if recipient in self._queues:  # some still wait: it goes behind them
                self._queue(recipient, message)
                return Outcome.NOT_SENT
            if (outcome := await self._try(recipient, message)).waits:
                self._queue(recipient, message)
            return outcome

    async def try_once(self, recipient: str, message: SendMessage) -> Outcome:
        """Send now, or not at all, as for what's no use late. Never raises,
        once started."""
        async with self._locks[recipient]:
            return await self._try(recipient, message)

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
        """Try the waiting messages again, oldest first in each chat, and drop
        expired ones; but no more once Signal rate-limits the bot, as the
        rest would meet the limit too."""
        for recipient in list(self._queues):
            async with self._locks[recipient]:
                if recipient in self._queues:
                    await self._flush(recipient)
            if self._rate_limited:
                return

    async def probe(self) -> None:
        """While Signal rate-limits the bot: drop what has waited too long,
        then try the message that has waited longest, alone. Once it goes
        out, the limit is lifted, and the rest follow."""
        for recipient in list(self._queues):
            async with self._locks[recipient]:
                if (queue := self._queues.get(recipient)) is not None:
                    self._expire(recipient, queue)
                    if not queue:
                        del self._queues[recipient]
        waiting = [(q[0].queued_at, chat) for chat, q in self._queues.items() if q]
        if not waiting:
            return
        _at, recipient = min(waiting)
        async with self._locks[recipient]:
            if recipient in self._queues:
                await self._flush(recipient)
        if not self._rate_limited:
            await self.flush()

    def nudge(self) -> None:
        """Try again now, while Signal rate-limits the bot, as for an admin's
        command: they may have just lifted the limit. Not sooner than
        NUDGE_AFTER after the last try met it."""
        if not self._rate_limited or self._wake is None:
            return
        since = time.monotonic() - (self._limited_at or 0)
        if since >= NUDGE_AFTER.total_seconds():
            self._wake.set()

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
            self.discarded += 1
            logger.warning(
                "Dropped a message %s, not sent in %s", to_whom(recipient), max_age
            )

    async def _try(
        self, recipient: str, message: SendMessage, queued_at: datetime | None = None
    ) -> Outcome:
        if self._post is None:
            raise RuntimeError("The outbox isn't started")
        if queued_at is not None:
            with speaking(chat_language(recipient)):
                message = delayed(message, queued_at)
        outcome, timestamp = await self._post(recipient, message)
        if outcome is Outcome.GIVE_UP:
            self.given_up += 1
        if outcome is Outcome.RATE_LIMITED:
            if not self._rate_limited and self.on_rate_limited is not None:
                self.on_rate_limited()
            self._rate_limited = True
            self._limited_at = time.monotonic()
        if outcome is not Outcome.SENT:
            return outcome
        logger.debug("Sent a message to %s", recipient)
        if self._rate_limited:
            # The limit is lifted: the others go now too
            logger.info("Signal no longer rate-limits the bot")
            self._rate_limited = False
            if self._wake is not None:
                self._wake.set()
        if timestamp is not None:
            sent = Sent.of(timestamp, recipient, message)
            self.sent.add(sent)
            if self.on_sent is not None:
                self.on_sent(sent)
        if dropped := self._dropped.pop(recipient, 0):
            with speaking(chat_language(recipient)):
                notice = SendMessage(text=error_text(dropped_text(dropped)))
            if await self._try(recipient, notice) is not Outcome.SENT:
                self._dropped[recipient] += dropped
        return outcome

    def _start_retrying(self) -> None:
        if self._retrying is None or self._retrying.done():
            # Before the loop runs, so a nudge meanwhile wakes it
            self._wake = asyncio.Event()
            self._retrying = asyncio.create_task(self._retry_loop(self._wake))

    async def _retry_loop(self, wake: asyncio.Event) -> None:
        delays = retry_delays()
        limited = rate_limited_delays()
        while self._queues:
            if self._rate_limited:
                delay = next(limited)
            else:
                delay = next(delays)
                limited = rate_limited_delays()  # a new limit starts afresh
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(delay.total_seconds()):
                    await wake.wait()
            wake.clear()
            try:
                await (self.probe() if self._rate_limited else self.flush())
            except Exception:
                logger.exception("Retrying queued messages failed")
        # No await between the last check and this, so nothing queued since
        self._retrying = self._wake = None


def delayed(message: SendMessage, queued_at: datetime) -> SendMessage:
    """The message with a note that it's late. Added last, so that mention
    positions in the text still hold; in a styled message, as it shows."""
    at = queued_at.astimezone(get_settings().tz)
    note = _("⏳ Delayed: this message was due at {time}").format(time=f"{at:%H:%M}")
    if message.text_mode == TextMode.STYLED:
        note = escape(note)
    text = f"{message.text}\n\n{note}" if message.text else note
    return message.model_copy(update={"text": text})


def dropped_text(count: int) -> str:
    """That count messages waited send_retry_hours and were dropped, as the
    chat is told, and the health checks."""
    hours = get_settings().send_retry_hours
    return ngettext(
        "{count} message could not be delivered within {hours} hours and was discarded",
        "{count} messages could not be delivered within {hours} hours and were "
        "discarded",
        count,
    ).format(count=count, hours=f"{hours:g}")


outbox = Outbox()


class PerChat(SendMessage):
    """A message some chats get with a text of their own, such as /today's,
    with the birthdays of those in a group: texts by chat, as the outbox
    knows it, and for the rest, its text."""

    texts: dict[str, str] = Field(default_factory=dict[str, str])


def for_chat(message: SendMessage, chat: str) -> SendMessage:
    """The message as the chat gets it."""
    if not isinstance(message, PerChat):
        return message
    fields = {name: getattr(message, name) for name in SendMessage.model_fields}
    text = message.texts.get(chat, message.text)
    return SendMessage.model_validate(fields | {"text": text})


def chat_of(bot: SignalBot, recipient: str) -> str:
    """The recipient as the outbox knows it: a group by its group.… ID."""
    return bot.groups.resolve(recipient) or recipient


def members(bot: SignalBot, group: str) -> list[str] | None:
    """A group's members but the bot, each once, which signal-cli-rest-api
    lists by phone number, or without one, by Signal ID, the bot as account
    has it then; None for a group the bot isn't in."""
    found = next((g for g in bot.groups if g.id == group and g.member), None)
    if found is None:
        return None
    return [m for m in dict.fromkeys(found.members) if m != get_settings().account]


def chats_of(context: DataMessageContext) -> set[str]:
    """The chat the command came from, as the outbox knows it. A direct chat
    may be known by phone number or by ID."""
    message = context.message
    if message.is_group():
        return {chat_of(context.bot, message.source_or_group_id())}
    return {who for who in (message.source_uuid, message.source_number) if who}


def language_here(context: DataMessageContext) -> str:
    """The code of the language the bot speaks in the chat the message came
    from: a group's own, a person's own, or else the setting's."""
    message = context.message
    if message.is_group():
        return chat_language(chat_of(context.bot, message.source_or_group_id()))
    return chat_language(message.source_number, message.source_uuid)


def chat_id(context: DataMessageContext) -> str:
    """The chat the command came from, as the bot keeps it, as timers do: a
    group by its group.… ID, a person by phone number, else by ID."""
    message = context.message
    if message.is_group():
        return chat_of(context.bot, message.source_or_group_id())
    return message.source_number or message.source_uuid or ""


async def send(bot: SignalBot, recipient: str, message: SendMessage) -> Outcome:
    """Send to a contact or group, as the chat gets it, its mentions made
    (styles.mentioned()), retrying while Signal can't be reached: what became
    of it. Never raises. A message with nothing in it, as a post with no text
    for the chat, as /today's on a day with nothing special there, isn't
    sent."""
    chat = chat_of(bot, recipient)
    message = mentioned(for_chat(message, chat))
    if not (message.text or message.base64_attachments or message.attachments):
        logger.debug("Nothing to send %s", to_whom(chat))
        return Outcome.SENT
    return await outbox.send(chat, message)


def arrival_delay(context: DataMessageContext) -> float:
    """Seconds the command took to reach the bot. Its timestamp is from the
    sender's clock, so this includes any difference in clocks."""
    return time.time() - context.message.timestamp / 1000


# While a timer, /run or a special runs a command, its answers are collected
# here, for it to post, rather than sent to whoever "sent" the command
collected: ContextVar[list[SendMessage] | None] = ContextVar("collected", default=None)
# While a command from nejomibot-chat runs, its answers are kept here, for
# the terminal, rather than sent: otherwise it runs as in a direct chat
to_terminal: ContextVar[list[SendMessage] | None] = ContextVar(
    "to_terminal", default=None
)


def from_signal() -> bool:
    """Whether the command running came in a message from Signal, unlike a
    timer's, /run's, a special's or nejomibot-chat's."""
    return collected.get() is None and to_terminal.get() is None


@dataclass
class Draw:
    """What a timer's or /run's command picks at random, the same in each
    language it runs in, for the chats that speak it: each run draws from
    one seed, and what one marks used, such as a photo of the round, stays
    unused for the next, which then picks the same."""

    seed: int = field(default_factory=lambda: random.getrandbits(64))
    used: set[str] = field(default_factory=set[str])
    chance: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.again()

    def again(self) -> None:
        """Draw anew from the seed, for the run in the next language."""
        self.chance = random.Random(self.seed)


drawn: ContextVar[Draw | None] = ContextVar("drawn", default=None)
anywhere = random.Random()


def chance() -> random.Random:
    """What random picks come from: while a command runs in a language of
    several, its draw's; else anywhere."""
    return draw.chance if (draw := drawn.get()) else anywhere


async def reply(context: DataMessageContext, message: SendMessage) -> None:
    """Send to the chat the command came from, or where it collects its
    answers. Never raises."""
    if (answers := collected.get()) is None:
        answers = to_terminal.get()
    if answers is not None:
        answers.append(message)
        return
    await send(context.bot, context.message.source_or_group_id(), message)
