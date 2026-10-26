"""The bot's health: whether signal-cli-rest-api answers, whether the bot
itself runs and its messages go out, whether Signal's servers answer for its
account, and whether the bot hears receipts and phones confirm its messages
(delivery.py). /status starts with these checks.

The bot runs them every healthcheck_minutes, the first time once signalbot is
ready. Each time it asks Signal's servers one thing: the account's linked
devices. The bot check tells of each send the outbox gave up on, and of each
message it dropped, once: in the first round after. The bot keeps the latest
result, only in memory. With healthcheck_url set, it also reports each to a
health check service such as healthchecks.io: it pings the URL when all
passed, or URL/fail with what failed, so the service warns when something
fails, or when the pings stop. Each ping says how each check went, then what
runs, as /status does: the versions of the bot, signalbot, Python and
signal-cli-rest-api, how long the bot, and so its container, has been up,
and the memory it uses.

The container's health check (healthcheck.py) asks something else: whether
the bot works, so whether restarting it could help, as a container runtime
may restart it when it doesn't. The answer has the latest result too.
"""

import asyncio
import contextlib
import logging
import platform
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import cast

import aiohttp
from signalbot import About, SignalBot

from . import healthcheck, system
from .account import Device, fetch_devices
from .client import client
from .config import get_settings
from .delivery import receipts
from .i18n import _, format_duration, format_file_size, ngettext
from .messages import describe, dropped_text, outbox

logger = logging.getLogger(__name__)

# About when the bot started, and so its container: the bot is its process
STARTED = datetime.now(UTC)
CHECK_TIMEOUT = 20  # seconds a check may take, so a stuck service can't hold it
SLOW = 1.0  # seconds: a check that takes this long says so
# A message waiting this long to be sent means the bot can't send
WAITING_TOO_LONG = timedelta(minutes=15)
PING_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Checks are late, so something's stuck, when the last was more than twice
# healthcheck_minutes ago and this
LATE = timedelta(minutes=1)
MEMORY_FULL = 0.9  # fraction of the memory limit in use
# signal-cli-rest-api up to this crashes on overlapping requests (#885), and
# its native signal-cli can't list linked devices (signal-cli#2119), as the
# Signal check does. Builds after it have "unset" for their version.
LAST_TOO_OLD = (0, 101)


class CheckFailed(Exception):
    """A check ran and found a problem, which the message describes."""


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    seconds: float | None = None  # how long it took, if it was timed

    @property
    def shown(self) -> str:
        """What it found, and how long it took, if that was a while."""
        if self.seconds is None or self.seconds < SLOW:
            return self.detail
        return _("{detail}, in {seconds} s").format(
            detail=self.detail, seconds=f"{self.seconds:.1f}"
        )


async def run_check(name: str, check: Callable[[], Awaitable[str]]) -> Check:
    """Run and time a check. It returns what it found, or raises."""
    start = time.monotonic()
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            detail = await check()
    except TimeoutError:
        logger.warning("Check %s timed out", name)
        return Check(name, ok=False, detail=_("timed out"))
    except Exception as e:
        logger.warning("Check %s failed: %s", name, describe(e))
        return Check(name, ok=False, detail=describe(e))
    return Check(name, ok=True, detail=detail, seconds=time.monotonic() - start)


def is_too_old(version: str) -> bool:
    """A signal-cli-rest-api release up to LAST_TOO_OLD."""
    try:
        return tuple(int(part) for part in version.split(".")) <= LAST_TOO_OLD
    except ValueError:
        return False  # "unset", for a build after a release


@dataclass(frozen=True)
class Health:
    checks: list[Check]
    about: About | None  # signal-cli-rest-api's, if it answered
    devices: list[Device]  # the account's linked devices, if Signal answered
    # The outbox's sends given up and messages dropped since the start, as
    # the bot check saw them: the next one tells of those after
    given_up: int = 0
    discarded: int = 0

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if not check.ok]


def bot_check(bot: SignalBot, now: datetime, before: Health | None = None) -> Check:
    """The bot itself: signalbot has started, which it only does once
    signal-cli-rest-api has the account, no message has waited long to be
    sent, and since the check before, the outbox gave up on no send and
    dropped no message."""
    name = _("Bot")
    # signalbot leaves the task's type open
    started = cast("asyncio.Task[object] | None", bot.init_task)  # pyright: ignore[reportUnknownMemberType]
    if started is None or not started.done():
        return Check(
            name,
            ok=False,
            detail=_("starting: waiting for signal-cli-rest-api and the account"),
        )
    problems: list[str] = []
    if (oldest := outbox.oldest()) and now - oldest > WAITING_TOO_LONG:
        waiting = len(outbox)
        detail = ngettext(
            "{count} message queued, the oldest for {duration}",
            "{count} messages queued, the oldest for {duration}",
            waiting,
        ).format(count=waiting, duration=format_duration(now - oldest))
        if outbox.rate_limited:
            detail += ". " + _(
                "rate-limited by Signal: run nejomibot-account rate-limit to lift "
                "the limit"
            )
        problems.append(detail)
    if given_up := outbox.given_up - (before.given_up if before else 0):
        problems.append(
            ngettext(
                "{count} message may not have arrived, as sending it failed",
                "{count} messages may not have arrived, as sending them failed",
                given_up,
            ).format(count=given_up)
        )
    if discarded := outbox.discarded - (before.discarded if before else 0):
        problems.append(dropped_text(discarded))
    if problems:
        return Check(name, ok=False, detail=". ".join(problems))
    return Check(name, ok=True, detail=_("running"))


def delivery_check(now: datetime) -> Check:
    """The bot hears the receipts for its messages, on a websocket to where
    messages to it come from too, and phones confirm what it sends."""
    name = _("Delivery")
    every = timedelta(minutes=get_settings().healthcheck_minutes)
    if (lost := receipts.lost) and now - lost > every:
        detail = _(
            "no receipts heard for {duration}: the websocket to "
            "signal-cli-rest-api fails, so messages to the bot may be lost too"
        ).format(duration=format_duration(now - lost))
        return Check(name, ok=False, detail=detail)
    if since := receipts.unconfirmed():
        detail = _(
            "no phone has confirmed any message the bot sent in the last "
            "{duration}: they may not arrive, or their receipts may not reach "
            "the bot"
        ).format(duration=format_duration(now - since))
        return Check(name, ok=False, detail=detail)
    if receipts.since is None:
        return Check(name, ok=True, detail=_("connecting to signal-cli-rest-api"))
    return Check(name, ok=True, detail=_("receipts heard"))


async def check_health(bot: SignalBot, before: Health | None = None) -> Health:
    """The health checks; of the outbox's losses, those since the check
    before."""
    found_about: list[About] = []
    found_devices: list[Device] = []

    async def signal_api() -> str:
        about = await bot.general.about()
        found_about.append(about)
        if about.mode != "json-rpc":
            raise CheckFailed(
                _("version {version} in {mode} mode, not json-rpc").format(
                    version=about.version, mode=about.mode
                )
            )
        if is_too_old(about.version):
            raise CheckFailed(
                _(
                    "version {version} is not supported: a later version is required"
                ).format(version=about.version)
            )
        return _("version {version}").format(version=about.version)

    async def signal() -> str:
        found_devices.extend(devices := await fetch_devices())
        return ngettext(
            "the account has {count} device",
            "the account has {count} devices",
            len(devices),
        ).format(count=len(devices))

    api_check, signal_check = await asyncio.gather(
        run_check("signal-cli-rest-api", signal_api),
        run_check(_("Signal"), signal),
    )
    now = datetime.now(UTC)
    return Health(
        checks=[
            api_check,
            bot_check(bot, now, before),
            signal_check,
            delivery_check(now),
        ],
        about=found_about[0] if found_about else None,
        devices=found_devices,
        given_up=outbox.given_up,
        discarded=outbox.discarded,
    )


def report_text(checks: list[Check]) -> str:
    return "\n".join(
        f"{'OK' if check.ok else 'FAILED'} {check.name}: {check.shown}"
        for check in checks
    )


def version_lines(about: About | None) -> list[str]:
    """The bot's versions, and signal-cli-rest-api's. signal-cli's isn't
    known: signal-cli-rest-api doesn't say."""
    api = (
        _("signal-cli-rest-api {version}, {mode} mode").format(
            version=about.version, mode=about.mode
        )
        if about
        else _("signal-cli-rest-api: no answer")
    )
    return [
        f"nejomibot {version('nejomibot')}",
        f"signalbot {version('signalbot')} · Python {platform.python_version()}",
        api,
    ]


def up_since(start: datetime) -> str:
    """Up how long since start, and since when, in the bot's time zone: the
    bot's uptime, or the host's."""
    return _("Up {duration}, since {time}").format(
        duration=format_duration(datetime.now(UTC) - start),
        time=f"{start.astimezone(get_settings().tz):%Y-%m-%d %H:%M}",
    )


def memory_check() -> Check:
    """The bot's memory, and the limit on it, if there is one. Quick enough
    for the event loop: /proc and /sys aren't on a disk."""
    name = _("Bot memory")
    status = system.proc_fields(system.PROC / "self/status")
    if "VmRSS" not in status:
        return Check(name, ok=True, detail=_("unknown"))
    rss = status["VmRSS"]
    detail = format_file_size(rss)
    if limit := system.memory_limit():
        detail = _("{used} of {limit} limit").format(
            used=detail, limit=format_file_size(limit)
        )
    if "VmHWM" in status:
        peak = _("(peak {peak})").format(peak=format_file_size(status["VmHWM"]))
        detail += f" {peak}"
    ok = not limit or rss / limit < MEMORY_FULL
    return Check(name, ok=ok, detail=detail)


def ping_text(health: Health) -> str:
    """For the health check service: how each check went, then what runs,
    since when, and in how much memory, as /status says it."""
    memory = memory_check()
    lines = [
        *version_lines(health.about),
        up_since(STARTED),
        f"{memory.name}: {memory.detail}",
    ]
    return report_text(health.checks) + "\n\n" + "\n".join(lines)


async def ping(url: str, text: str) -> None:
    """Tell the health check service. Never raises: it notices when the pings
    stop."""
    try:
        # A str goes as text/plain; charset=utf-8
        async with client.session().post(
            url, data=text, timeout=PING_TIMEOUT
        ) as response:
            response.raise_for_status()
    except Exception as e:
        logger.warning("Could not ping the health check: %s", describe(e))


async def listen(answer: Callable[[], str]) -> asyncio.Server | None:
    """Answer the container's health check with answer() until the server is
    closed, or None if the bot can't."""

    async def reply(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            writer.write(answer().encode())
            await writer.drain()
        except ConnectionError:
            pass  # it gave up waiting
        finally:
            writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()

    try:
        return await asyncio.start_unix_server(reply, path=healthcheck.SOCKET)
    except OSError as e:
        logger.warning("Can't answer the container's health check: %r", e)
        return None


@contextlib.asynccontextmanager
async def answering(answer: Callable[[], str]) -> AsyncGenerator[None]:
    """Answer the container's health check with answer() meanwhile."""
    server = await listen(answer)
    try:
        yield
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()


class Rounds:
    """The bot's health checks, run every healthcheck_minutes. The latest is
    kept for the container's health check, which asks over a socket."""

    def __init__(self) -> None:
        self.latest: tuple[datetime, Health] | None = None
        self.started: datetime | None = None  # when it began answering
        self.server: asyncio.Server | None = None

    @property
    def reported(self) -> Health | None:
        """What the latest round found, if one ran: the next tells of what
        the outbox lost since."""
        return self.latest[1] if self.latest else None

    async def run(self, bot: SignalBot) -> None:
        """Check the bot's health, and report it to healthcheck_url, if set."""
        health = await check_health(bot, self.reported)
        self.latest = (datetime.now(UTC), health)
        if failed := health.failed:
            logger.warning("Health check failed: %s", report_text(failed))
        if url := get_settings().healthcheck_url:
            await ping(f"{url.rstrip('/')}/fail" if failed else url, ping_text(health))

    def answer(self, now: datetime) -> str:
        """For the container's health check: OK or FAILED, whether the bot
        works, then how the latest check went. The bot works if it answers in
        time, which the container's health check sees to, and its checks run
        on time, as they don't when it's stuck. What they find doesn't count:
        no restart of the bot helps when Signal or signal-cli-rest-api fails,
        and a restart could lose the messages that have waited less than half
        a minute, which aren't on disk yet."""
        every = timedelta(minutes=get_settings().healthcheck_minutes)
        if self.latest is None:
            waited = now - (self.started or now)
            if waited > 2 * every + LATE:
                return (
                    f"FAILED: no health check in {format_duration(waited)}, but "
                    f"they run every {format_duration(every)}: the bot is stuck"
                )
            return "OK: starting, no health check yet"
        at, health = self.latest
        age = now - at
        report = report_text(health.checks)
        if age > 2 * every + LATE:
            return (
                f"FAILED: the last health check was {format_duration(age)} ago, "
                f"but they run every {format_duration(every)}: the bot is "
                f"stuck\n{report}"
            )
        return (
            f"OK: the bot runs; its latest health check, {format_duration(age)} "
            f"ago:\n{report}"
        )

    async def serve(self, bot: SignalBot) -> None:
        """Answer the container's health check, and run the first health check
        once signalbot is ready."""
        self.started = datetime.now(UTC)
        self.server = await listen(lambda: self.answer(datetime.now(UTC)))
        await bot.wait_until_ready()
        await self.run(bot)


rounds = Rounds()


async def stop() -> None:
    """Stop answering the container's health check, as the bot stops."""
    if (server := rounds.server) is not None:
        server.close()
        await server.wait_closed()
        rounds.server = None


def start(bot: SignalBot) -> None:
    """Check the bot's health every healthcheck_minutes, and once signalbot is
    ready, and answer the container's health check."""
    minutes = get_settings().healthcheck_minutes
    # However late they come, as when the event loop is busy for a moment:
    # APScheduler would skip a run more than a second late, and the
    # container's health check fails when rounds are missed. Once, as soon as
    # the scheduler starts:
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        rounds.serve,
        args=[bot],
        id="health-serve",
        misfire_grace_time=None,
        replace_existing=True,
    )
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        rounds.run,
        "interval",
        args=[bot],
        minutes=minutes,
        id="health-checks",
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    logger.info("Checking the bot's health every %d minutes", minutes)
