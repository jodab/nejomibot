"""The bot's health: whether signal-cli-rest-api answers, whether the bot
itself runs, and whether Signal's servers answer for its account. /status
starts with these checks.

The bot runs them every healthcheck_minutes, the first time once signalbot is
ready. Each time it asks Signal's servers one thing: the account's linked
devices. It keeps the latest result, only in memory. With healthcheck_url
set, it also reports each to a health check service such as healthchecks.io:
it pings the URL when all passed, or URL/fail with what failed, so the
service warns when something fails, or when the pings stop.

The container's health check (healthcheck.py) asks something else: whether
the bot works, so whether restarting it could help, as a container runtime
may restart it when it doesn't. The answer has the latest result too.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import aiohttp
from signalbot import About, SignalBot

from . import healthcheck
from .account import Device, fetch_devices
from .client import client
from .config import get_settings
from .i18n import _, ngettext
from .messages import describe, outbox

logger = logging.getLogger(__name__)

CHECK_TIMEOUT = 20  # seconds a check may take, so a stuck service can't hold it
SLOW = 1.0  # seconds: a check that takes this long says so
# A message waiting this long to be sent means the bot can't send
WAITING_TOO_LONG = timedelta(minutes=15)
PING_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Checks are late, so something's stuck, when the last was more than twice
# healthcheck_minutes ago and this
LATE = timedelta(minutes=1)
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


def format_duration(duration: timedelta) -> str:
    """E.g. '3 d 4 h', '4 h 12 min', '12 min' or '45 s'."""
    seconds = int(duration.total_seconds())
    if seconds < 60:
        return _("{seconds} s").format(seconds=seconds)
    hours, minutes = divmod(seconds // 60, 60)
    days, hours = divmod(hours, 24)
    if days:
        return _("{days} d {hours} h").format(days=days, hours=hours)
    if hours:
        return _("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
    return _("{minutes} min").format(minutes=minutes)


def is_too_old(version: str) -> bool:
    """A signal-cli-rest-api release up to LAST_TOO_OLD."""
    try:
        return tuple(int(part) for part in version.split(".")) <= LAST_TOO_OLD
    except ValueError:
        return False  # "unset", for a build after a release


def bot_check(bot: SignalBot, now: datetime) -> Check:
    """The bot itself: signalbot has started, which it only does once
    signal-cli-rest-api has the account, and no message has waited long to
    be sent."""
    name = _("Bot")
    # signalbot leaves the task's type open
    started = cast("asyncio.Task[object] | None", bot.init_task)  # pyright: ignore[reportUnknownMemberType]
    if started is None or not started.done():
        return Check(
            name,
            ok=False,
            detail=_(
                "still starting: signalbot waits for signal-cli-rest-api and the "
                "account"
            ),
        )
    if (oldest := outbox.oldest()) and now - oldest > WAITING_TOO_LONG:
        waiting = len(outbox)
        detail = ngettext(
            "{count} message waiting to be sent, the first for {duration}",
            "{count} messages waiting to be sent, the first for {duration}",
            waiting,
        ).format(count=waiting, duration=format_duration(now - oldest))
        return Check(name, ok=False, detail=detail)
    return Check(name, ok=True, detail=_("running"))


@dataclass(frozen=True)
class Health:
    checks: list[Check]
    about: About | None  # signal-cli-rest-api's, if it answered
    devices: list[Device]  # the account's linked devices, if Signal answered

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if not check.ok]


async def check_health(bot: SignalBot) -> Health:
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
                _("version {version} is too old: the bot needs a later one").format(
                    version=about.version
                )
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
    return Health(
        checks=[api_check, bot_check(bot, datetime.now(UTC)), signal_check],
        about=found_about[0] if found_about else None,
        devices=found_devices,
    )


def report_text(checks: list[Check]) -> str:
    return "\n".join(
        f"{'OK' if check.ok else 'FAILED'} {check.name}: {check.shown}"
        for check in checks
    )


async def ping(url: str, text: str) -> None:
    """Tell the health check service. Never raises: it notices when the pings
    stop."""
    try:
        async with client.session().post(
            url, data=text.encode(), timeout=PING_TIMEOUT
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

    async def run(self, bot: SignalBot) -> None:
        """Check the bot's health, and report it to healthcheck_url, if set."""
        health = await check_health(bot)
        self.latest = (datetime.now(UTC), health)
        text = report_text(health.checks)
        if failed := health.failed:
            logger.warning("Health check failed: %s", report_text(failed))
        if url := get_settings().healthcheck_url:
            await ping(f"{url.rstrip('/')}/fail" if failed else url, text)

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
