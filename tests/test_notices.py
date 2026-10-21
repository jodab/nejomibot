import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from aiohttp import web
from helpers import DAY_MS, ME, NOW_MS, FakeApi
from signalbot import SendMessage, SignalBot

from nejomibot import notices
from nejomibot.config import get_settings
from nejomibot.messages import Outcome
from nejomibot.notices import (
    RATE_LIMIT_AGAIN,
    Notices,
    Run,
    read_run,
    start_text,
)

ADMIN = "+46700000009"
STARTED = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)  # 08:00 in Stockholm
STOPPED = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
UNCLEAN = (
    "⚠️ Up again, after a stop that wasn't clean, such as a crash, a kill or a "
    "power cut. It had run since 2026-10-19 08:00. Messages that had waited less "
    "than half a minute to be sent may be lost."
)


@pytest.fixture(autouse=True)
def admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()


class Outbox:
    """Where the notices go, instead of Signal: what's tried once, as Signal
    rate-limits the bot."""

    def __init__(self) -> None:
        self.on_rate_limited: Any = None
        self.tried: list[tuple[str, str]] = []

    async def try_once(self, recipient: str, message: SendMessage) -> Outcome:
        self.tried.append((recipient, message.text or ""))
        return Outcome.RATE_LIMITED


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(notices, "outbox", box)
    return box


@pytest.fixture
def told(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """What the admins are told, waiting to be sent if need be."""
    found: list[tuple[str, str]] = []

    async def send(bot: SignalBot, recipient: str, message: SendMessage) -> Outcome:
        found.append((recipient, message.text or ""))
        return Outcome.SENT

    monkeypatch.setattr(notices, "send", send)
    return found


@pytest.mark.parametrize(
    ("previous", "text"),
    [
        # A first start, or debug mode, whose files are new each time
        (None, None),
        # A restart like any other
        (Run(version="0.99.0", started=STARTED, stopped=STOPPED), None),
        (
            Run(version="0.98.0", started=STARTED, stopped=STOPPED),
            "🔄 Updated: nejomibot 0.98.0 → 0.99.0.",
        ),
        (Run(version="0.99.0", started=STARTED), UNCLEAN),
        (
            Run(version="0.98.0", started=STARTED),
            f"🔄 Updated: nejomibot 0.98.0 → 0.99.0.\n\n{UNCLEAN}",
        ),
    ],
)
def test_what_a_start_tells(previous: Run | None, text: str | None) -> None:
    now = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
    assert start_text(previous, Run(version="0.99.0", started=now)) == text


@pytest.mark.usefixtures("outbox")
async def test_each_run_is_kept(bot: SignalBot) -> None:
    keeper = Notices()
    keeper.start(bot)
    run = read_run()
    assert run is not None and run.stopped is None
    keeper.stopped()
    stopped = read_run()
    assert stopped is not None and stopped.stopped is not None
    assert stopped.started == run.started
    path = get_settings().data_file("run.json")
    assert path.stat().st_mode & 0o777 == 0o600
    # The next start knows the one before
    keeper = Notices()
    keeper.start(bot)
    assert keeper.previous == stopped
    assert keeper.looked == stopped.stopped


async def test_a_run_file_it_can_t_read(caplog: pytest.LogCaptureFixture) -> None:
    get_settings().data_file("run.json").write_text("{")
    assert read_run() is None
    assert "Could not read" in caplog.text


async def test_changed_safety_numbers(
    bot: SignalBot,
    signal_api: FakeApi,
    told: list[tuple[str, str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="nejomibot")
    keeper = Notices()
    # Bob's changed a day ago, and isn't trusted
    keeper.looked = datetime.fromtimestamp((NOW_MS - 2 * DAY_MS) / 1000, UTC)
    await keeper.look_at_safety_numbers(bot)
    assert told == [
        (
            ADMIN,
            "🔐 The safety number of Bob Berg has changed: they may have a new "
            "phone, or it may not be them. The bot can't send to them until it's "
            "trusted: compare it with theirs with /contacts Bob Berg, then /trust.",
        )
    ]
    assert "Telling the admins of a changed safety number" in caplog.text
    assert "Bob" not in caplog.text
    # Told once
    told.clear()
    await keeper.look_at_safety_numbers(bot)
    assert told == []

    # When signal-cli-rest-api can't say, the next look looks from the last
    async def unavailable(request: web.Request) -> web.Response:
        return web.json_response({"error": "down"}, status=500)

    looked = keeper.looked
    signal_api.route("GET", f"/v1/identities/{ME}", unavailable)
    await keeper.look_at_safety_numbers(bot)
    assert keeper.looked == looked
    assert "Could not look at the safety numbers" in caplog.text


async def test_rate_limited(bot: SignalBot, outbox: Outbox) -> None:
    keeper = Notices()
    keeper.start(bot)
    # As the outbox says Signal starts rate-limiting the bot
    assert outbox.on_rate_limited is not None
    outbox.on_rate_limited()
    await asyncio.gather(*keeper.tasks)
    # Tried once, and not again for a while
    assert outbox.tried == [
        (
            ADMIN,
            "⚠️ Signal rate-limits the bot, so messages wait, and are tried every "
            "half hour. To lift the limit, run signal-account.sh rate-limit --to "
            "<your number> on the server, and solve the captcha.",
        )
    ]
    await keeper.rate_limited(bot)
    assert len(outbox.tried) == 1
    assert keeper.rate_limited_at is not None
    keeper.rate_limited_at -= RATE_LIMIT_AGAIN
    await keeper.rate_limited(bot)
    assert len(outbox.tried) == 2


async def test_served_once_ready(
    bot: SignalBot,
    signal_api: FakeApi,
    told: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ready() -> None:
        pass

    monkeypatch.setattr(bot, "wait_until_ready", ready)
    keeper = Notices()
    keeper.previous = Run(version="0.97.0", started=STARTED, stopped=STOPPED)
    keeper.run = Run(version="0.98.0", started=STOPPED)
    # Just now, as the fake API's safety numbers changed a day before the
    # test runs, whenever that is
    keeper.looked = datetime.now(UTC)
    await keeper.serve(bot)
    # The update, then the safety numbers changed since, of which there are none
    assert told == [(ADMIN, "🔄 Updated: nejomibot 0.97.0 → 0.98.0.")]
    job = cast(Any, bot.scheduler.get_job("notices-safety-numbers"))  # pyright: ignore[reportUnknownMemberType]
    assert job is not None
    assert str(job.trigger) == "interval[0:05:00]"
