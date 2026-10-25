import asyncio
import socket
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from helpers import ME, FakeApi, write
from signalbot import About, SignalBot

from nejomibot import bot as bot_module
from nejomibot import health, healthcheck
from nejomibot.bot import wait_for_account
from nejomibot.config import get_settings
from nejomibot.delivery import Receipts
from nejomibot.health import (
    Check,
    Health,
    Rounds,
    bot_check,
    check_health,
    delivery_check,
    is_too_old,
    run_check,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("duration", "text"),
    [
        (timedelta(seconds=59.9), "59 s"),
        (timedelta(seconds=60), "1 min"),
        (timedelta(minutes=72), "1 h 12 min"),
        (timedelta(days=3, hours=4, minutes=59), "3 d 4 h"),
    ],
)
def test_format_duration(duration: timedelta, text: str) -> None:
    assert health.format_duration(duration) == text


async def test_run_check_times_a_pass() -> None:
    async def check() -> str:
        return "fine"

    result = await run_check("Thing", check)
    assert result.ok
    assert result.detail == "fine"
    assert result.seconds is not None
    assert result.shown == "fine"  # it was quick


async def test_run_check_reports_a_failure() -> None:
    async def check() -> str:
        raise ConnectionRefusedError

    assert await run_check("Thing", check) == Check(
        "Thing", ok=False, detail="ConnectionRefusedError"
    )


async def test_run_check_gives_up_on_a_stuck_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> str:
        await asyncio.sleep(10)
        return "too late"

    monkeypatch.setattr(health, "CHECK_TIMEOUT", 0.01)
    result = await asyncio.wait_for(run_check("Thing", check), 1)
    assert result == Check("Thing", ok=False, detail="timed out")


async def started(bot: SignalBot) -> SignalBot:
    """The bot, as if signalbot had finished starting."""

    async def done() -> None:
        pass

    task = asyncio.create_task(done())
    await task
    bot.init_task = task
    return bot


class Waiting:
    """An outbox with messages waiting since then, and maybe rate-limited;
    with sends given up and messages dropped since the start."""

    def __init__(
        self,
        since: datetime | None,
        count: int,
        *,
        rate_limited: bool = False,
        given_up: int = 0,
        discarded: int = 0,
    ) -> None:
        self.since, self.count, self.rate_limited = since, count, rate_limited
        self.given_up, self.discarded = given_up, discarded

    def oldest(self) -> datetime | None:
        return self.since

    def __len__(self) -> int:
        return self.count


async def test_bot_check(bot: SignalBot, monkeypatch: pytest.MonkeyPatch) -> None:
    assert bot_check(bot, NOW) == Check(
        "Bot",
        ok=False,
        detail="starting: waiting for signal-cli-rest-api and the account",
    )
    await started(bot)
    assert bot_check(bot, NOW) == Check("Bot", ok=True, detail="running")

    # Messages may wait a while: Signal can be down for minutes
    monkeypatch.setattr(health, "outbox", Waiting(NOW - timedelta(minutes=14), 1))
    assert bot_check(bot, NOW).ok
    monkeypatch.setattr(health, "outbox", Waiting(NOW - timedelta(minutes=20), 2))
    assert bot_check(bot, NOW) == Check(
        "Bot", ok=False, detail="2 messages queued, the oldest for 20 min"
    )
    # Saying why, when it's Signal's limit, and what lifts it
    waiting = Waiting(NOW - timedelta(minutes=40), 1, rate_limited=True)
    monkeypatch.setattr(health, "outbox", waiting)
    assert bot_check(bot, NOW) == Check(
        "Bot",
        ok=False,
        detail="1 message queued, the oldest for 40 min. rate-limited by Signal: "
        "run signal-account.sh rate-limit to lift the limit",
    )


async def test_bot_check_tells_of_what_the_outbox_lost(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    await started(bot)
    lost = Waiting(NOW - timedelta(minutes=20), 1, given_up=3, discarded=1)
    monkeypatch.setattr(health, "outbox", lost)
    assert bot_check(bot, NOW) == Check(
        "Bot",
        ok=False,
        detail="1 message queued, the oldest for 20 min. 3 messages may not have "
        "arrived, as sending them failed. 1 message could not be delivered "
        "within 3 hours and was discarded",
    )
    # Only what's new since the check before
    before = Health([], None, [], given_up=2, discarded=1)
    lost.since = None
    assert bot_check(bot, NOW, before) == Check(
        "Bot", ok=False, detail="1 message may not have arrived, as sending it failed"
    )
    before = Health([], None, [], given_up=3, discarded=1)
    assert bot_check(bot, NOW, before) == Check("Bot", ok=True, detail="running")


async def test_each_loss_is_told_of_in_one_round(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    await started(bot)
    monkeypatch.setattr(health, "outbox", Waiting(None, 0, given_up=1))
    rounds = Rounds()
    await rounds.run(bot)
    assert (first := rounds.reported) is not None
    assert first.failed == [
        Check(
            "Bot",
            ok=False,
            detail="1 message may not have arrived, as sending it failed",
        )
    ]
    await rounds.run(bot)
    assert (second := rounds.reported) is not None
    assert second.failed == []


def test_delivery_check(monkeypatch: pytest.MonkeyPatch) -> None:
    keeper = Receipts()
    monkeypatch.setattr(health, "receipts", keeper)
    assert delivery_check(NOW) == Check(
        "Delivery", ok=True, detail="connecting to signal-cli-rest-api"
    )
    keeper.since = NOW - timedelta(days=1)
    assert delivery_check(NOW) == Check("Delivery", ok=True, detail="receipts heard")

    # Not for a moment, as while signal-cli-rest-api restarts; but not for
    # longer than healthcheck_minutes
    keeper.since, keeper.lost = None, NOW - timedelta(minutes=5)
    assert delivery_check(NOW).ok
    keeper.lost = NOW - timedelta(minutes=12)
    assert delivery_check(NOW) == Check(
        "Delivery",
        ok=False,
        detail="no receipts heard for 12 min: the websocket to signal-cli-rest-api "
        "fails, so messages to the bot may be lost too",
    )

    # No phone confirmed three in a row within unconfirmed_hours, nor any
    # message sent since
    keeper.since, keeper.lost = NOW - timedelta(days=1), None
    keeper.settled.extend(NOW - timedelta(hours=hours) for hours in (14, 13, 12))
    assert delivery_check(NOW) == Check(
        "Delivery",
        ok=False,
        detail="no phone has confirmed any message the bot sent in the last "
        "14 h 0 min: they may not arrive, or their receipts may not reach the bot",
    )


async def test_all_is_well(bot: SignalBot, signal_api: FakeApi) -> None:
    result = await check_health(await started(bot))
    assert [(c.name, c.ok, c.detail) for c in result.checks] == [
        ("signal-cli-rest-api", True, "version unset"),
        ("Bot", True, "running"),
        ("Signal", True, "the account has 2 devices"),
        ("Delivery", True, "connecting to signal-cli-rest-api"),
    ]
    assert result.about is not None and result.about.version == "unset"
    assert [device.id for device in result.devices] == [2, 1]
    assert result.failed == []
    # Signal's servers were asked one thing
    assert signal_api.bodies("GET", f"/v1/devices/{ME}") == [None]


async def test_signal_cant_be_reached(bot: SignalBot, signal_api: FakeApi) -> None:
    async def unregistered(request: web.Request) -> web.Response:
        error = {"error": f"User {ME} is not registered."}
        return web.json_response(error, status=400)

    signal_api.route("GET", f"/v1/devices/{ME}", unregistered)
    result = await check_health(await started(bot))
    assert result.failed == [
        Check("Signal", ok=False, detail=f"User {ME} is not registered.")
    ]
    assert result.devices == []


async def test_signal_cli_rest_api_in_the_wrong_mode(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    signal_api.responses["/v1/about"]["mode"] = "normal"
    result = await check_health(await started(bot))
    [failed] = result.failed
    assert failed == Check(
        "signal-cli-rest-api",
        ok=False,
        detail="version unset in normal mode, not json-rpc",
    )
    assert result.about is not None  # it answered


@pytest.mark.parametrize(
    ("version", "too_old"),
    [
        ("0.101", True),
        ("0.99", True),
        ("0.102", False),
        ("1.0", False),
        ("unset", False),
    ],
)
def test_is_too_old(version: str, too_old: bool) -> None:
    assert is_too_old(version) is too_old


async def test_signal_cli_rest_api_too_old(bot: SignalBot, signal_api: FakeApi) -> None:
    signal_api.responses["/v1/about"]["version"] = "0.101"
    [failed] = (await check_health(await started(bot))).failed
    assert failed.detail == (
        "version 0.101 is not supported: a later version is required"
    )


def test_version_lines() -> None:
    about = About(
        build=2, capabilities={}, mode="json-rpc", version="0.101", versions=["v1"]
    )
    assert health.version_lines(about)[0] == f"nejomibot {version('nejomibot')}"
    assert health.version_lines(about)[1].startswith(
        f"signalbot {version('signalbot')} · Python 3."
    )
    assert health.version_lines(about)[2] == (
        "signal-cli-rest-api 0.101, json-rpc mode"
    )
    assert health.version_lines(None)[2] == "signal-cli-rest-api: no answer"


def test_memory_check_near_limit(fake_system: Path) -> None:
    write(fake_system, "proc/self/cgroup", "0::/\n")
    write(fake_system, "sys/fs/cgroup/memory.max", str(100 * 1024**2))
    write(fake_system, "proc/self/status", "VmRSS: 95000 kB\nVmHWM: 96000 kB\n")
    assert health.memory_check() == Check(
        "Bot memory", ok=False, detail="92.8MB of 100.0MB limit (peak 93.8MB)"
    )


type Pings = list[tuple[str, str]]


@pytest.fixture
async def healthchecks(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Pings]:
    """A stand-in for healthchecks.io, which healthcheck_url points to. Yields
    the pings: the path, and what was sent along."""
    pings: Pings = []

    async def ping(request: web.Request) -> web.Response:
        pings.append((request.path, await request.text()))
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_post("/{path:.*}", ping)
    async with TestServer(app, host="127.0.0.1") as server:
        monkeypatch.setenv("NEJOMIBOT_HEALTHCHECK_URL", str(server.make_url("/uuid")))
        get_settings.cache_clear()
        yield pings


async def test_pings_when_all_is_well(
    bot: SignalBot,
    signal_api: FakeApi,
    healthchecks: Pings,
    fake_system: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(fake_system, "proc/self/status", "VmRSS: 71680 kB\nVmHWM: 74752 kB\n")
    monkeypatch.setattr(health, "STARTED", datetime.now(UTC) - timedelta(hours=26))
    await Rounds().run(await started(bot))
    [(path, text)] = healthchecks
    assert path == "/uuid"
    checks, about = text.split("\n\n")
    assert checks.splitlines() == [
        "OK signal-cli-rest-api: version unset",
        "OK Bot: running",
        "OK Signal: the account has 2 devices",
        "OK Delivery: connecting to signal-cli-rest-api",
    ]
    # Then what runs, as /status says it: the versions, the uptime, the memory
    lines = about.splitlines()
    assert lines[0] == f"nejomibot {version('nejomibot')}"
    assert lines[2] == "signal-cli-rest-api unset, json-rpc mode"
    assert lines[3].startswith("Up 1 d 2 h, since ")
    assert lines[4:] == ["Bot memory: 70.0MB (peak 73.0MB)"]


async def test_pings_what_failed(
    bot: SignalBot,
    signal_api: FakeApi,
    healthchecks: Pings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await Rounds().run(bot)  # signalbot hasn't started
    [(path, text)] = healthchecks
    assert path == "/uuid/fail"
    assert "FAILED Bot: starting" in text
    assert "Health check failed: FAILED Bot: starting" in caplog.text


async def test_a_failed_ping_doesnt_raise(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing listens there, as without internet
    monkeypatch.setenv("NEJOMIBOT_HEALTHCHECK_URL", "http://127.0.0.1:1/uuid")
    get_settings.cache_clear()
    await Rounds().run(await started(bot))


async def test_checks_without_a_url_too(bot: SignalBot, signal_api: FakeApi) -> None:
    rounds = Rounds()
    await rounds.run(await started(bot))
    assert rounds.latest is not None
    assert signal_api.bodies("GET", f"/v1/devices/{ME}") == [None]


# The container's health check


def test_answer_before_the_first_check() -> None:
    rounds = Rounds()
    rounds.started = NOW
    assert rounds.answer(NOW) == "OK: starting, no health check yet"
    # Checks every 5 minutes: none in 12 minutes means the bot is stuck
    assert rounds.answer(NOW + timedelta(minutes=12)) == (
        "FAILED: no health check in 12 min, but they run every 5 min: the bot is stuck"
    )


async def test_answer_says_how_the_latest_check_went(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    rounds = Rounds()
    await rounds.run(await started(bot))
    assert rounds.latest is not None
    at = rounds.latest[0]
    assert rounds.answer(at + timedelta(minutes=2)).splitlines() == [
        "OK: the bot runs; its latest health check, 2 min ago:",
        "OK signal-cli-rest-api: version unset",
        "OK Bot: running",
        "OK Signal: the account has 2 devices",
        "OK Delivery: connecting to signal-cli-rest-api",
    ]
    # Checks every 5 minutes: one 12 minutes ago means the bot is stuck
    assert rounds.answer(at + timedelta(minutes=12)).startswith(
        "FAILED: the last health check was 12 min ago, but they run every 5 min: "
        "the bot is stuck\nOK "
    )


async def test_what_a_check_finds_doesnt_fail_the_bot(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    # No restart of the bot helps when Signal fails, nor while signalbot
    # starts, which it retries itself
    async def unregistered(request: web.Request) -> web.Response:
        error = {"error": f"User {ME} is not registered."}
        return web.json_response(error, status=400)

    signal_api.route("GET", f"/v1/devices/{ME}", unregistered)
    rounds = Rounds()
    await rounds.run(bot)
    assert rounds.latest is not None
    assert rounds.answer(rounds.latest[0]).splitlines() == [
        "OK: the bot runs; its latest health check, 0 s ago:",
        "OK signal-cli-rest-api: version unset",
        "FAILED Bot: starting: waiting for signal-cli-rest-api and the account",
        f"FAILED Signal: User {ME} is not registered.",
        "OK Delivery: connecting to signal-cli-rest-api",
    ]


async def run_health_check(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """What nejomibot-healthcheck exits with, and says."""
    with pytest.raises(SystemExit) as exited:
        await asyncio.to_thread(healthcheck.main)
    code = exited.value.code
    assert isinstance(code, int)
    return code, capsys.readouterr().out


async def test_the_container_asks_the_bot(
    bot: SignalBot, signal_api: FakeApi, capsys: pytest.CaptureFixture[str]
) -> None:
    rounds = Rounds()
    # Answers, and checks once signalbot is ready
    await rounds.serve(await started(bot))
    try:
        code, said = await run_health_check(capsys)
    finally:
        assert rounds.server is not None
        rounds.server.close()
        await rounds.server.wait_closed()
    assert code == 0
    assert said.splitlines()[0] == "OK: the bot runs; its latest health check, 0 s ago:"
    assert "OK Signal: the account has 2 devices" in said


async def test_the_container_hears_that_the_bot_waits(
    signal_api: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # It may wait long for the account on a new install, which a restart
    # would cut short, as it's set up in the bot's container
    monkeypatch.setattr(bot_module, "WAIT_RETRY", 0.01)
    signal_api.responses["/v1/accounts"] = []
    waiting = asyncio.create_task(wait_for_account())
    await signal_api.wait_for("GET", "/v1/accounts", 2)
    code, said = await run_health_check(capsys)
    assert code == 0
    assert said == (
        f"OK: waiting: signal-cli-rest-api at {get_settings().signal_service} has "
        f"no account {ME} yet: register or link it with signal-account.sh setup\n"
    )

    # Then signalbot starts, and answers once it runs
    signal_api.responses["/v1/accounts"] = [ME]
    await asyncio.wait_for(waiting, 1)
    code, said = await run_health_check(capsys)
    assert code == 1
    assert said.startswith("FAILED: the bot doesn't answer")


async def test_the_container_hears_nothing_from_a_stuck_bot(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    socket_name: str,
) -> None:
    monkeypatch.setattr(healthcheck, "TIMEOUT", 0.1)
    # Its event loop is stuck: the socket listens, but nothing answers
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listening:
        listening.bind(socket_name)
        listening.listen()
        code, said = await run_health_check(capsys)
    assert code == 1
    assert said.startswith("FAILED: the bot doesn't answer (timed out)")


class Scheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def add_job(self, *args: Any, **kwargs: Any) -> None:
        self.jobs.append({"args": args, **kwargs})


class FakeBot:
    def __init__(self) -> None:
        self.scheduler = Scheduler()


def test_checks_every_few_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_HEALTHCHECK_MINUTES", "7")
    get_settings.cache_clear()
    bot = FakeBot()
    health.start(bot)  # pyright: ignore[reportArgumentType]
    serve, checks = bot.scheduler.jobs
    # Answering the container's health check from the start, and checking
    # once signalbot is ready
    assert serve["id"] == "health-serve"
    assert (checks["id"], checks["minutes"]) == ("health-checks", 7)


async def test_health_rounds_arent_skipped_when_late(bot: SignalBot) -> None:
    # Two missed rounds would make the container's health check fail
    health.start(bot)
    for job_id in ("health-serve", "health-checks"):
        job = cast(Any, bot.scheduler.get_job(job_id))  # pyright: ignore[reportUnknownMemberType]
        assert job.misfire_grace_time is None
