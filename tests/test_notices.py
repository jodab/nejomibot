import asyncio
import logging
import platform
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web
from helpers import DAY_MS, GROUP, ME, NOW_MS, FakeApi, make_jpeg
from signalbot import SendMessage, SignalBot, TextMode

from nejomibot import notices
from nejomibot.config import get_settings
from nejomibot.health import Check
from nejomibot.messages import Outcome
from nejomibot.notices import (
    QUIET,
    RATE_LIMIT_AGAIN,
    Notices,
    Run,
    previous_lines,
    read_run,
    start_text,
)
from nejomibot.timers import Timekeeper

ADMIN = "+46700000009"
STARTED = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)  # 08:00 in Stockholm
STOPPED = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
UNCLEAN = (
    "⚠️ The previous run, started {time}, did not shut down cleanly, as after a "
    "crash, a forced stop or a power failure. Messages queued for less than 30 "
    "seconds may have been lost."
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
    ("previous", "lines"),
    [
        # A first start, or debug mode, whose files are new each time
        (None, []),
        # A restart like any other
        (Run(version="0.99.0", started=STARTED, stopped=STOPPED), []),
        (
            Run(version="0.98.0", started=STARTED, stopped=STOPPED),
            ["🔄 Updated from 0.98.0"],
        ),
        (Run(version="0.99.0", started=STARTED), [UNCLEAN.format(time="08:00")]),
        (
            Run(version="0.98.0", started=STARTED),
            ["🔄 Updated from 0.98.0", UNCLEAN.format(time="08:00")],
        ),
    ],
)
def test_what_a_start_says_of_the_run_before(
    previous: Run | None, lines: list[str]
) -> None:
    assert previous_lines(previous, Run(version="0.99.0", started=NOW), NOW) == lines


async def test_a_start_s_notice(
    bot: SignalBot, photos_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The host's own state, as it could be anywhere
    monkeypatch.setattr(
        notices,
        "local_checks",
        lambda: [
            ("🕐", Check("Clock", ok=False, detail="not synchronized")),
            ("🧠", Check("Bot memory", ok=True, detail="70.0 MB")),
        ],
    )
    monkeypatch.setattr(notices, "host_line", lambda: "🖥️ Podman on bothost · aarch64")
    make_jpeg(photos_dir / "a.jpg")
    # A timer, and a line with a command the bot no longer has
    get_settings().timers_file.write_text(
        f"1 | daily 08:00 | {GROUP} | /ping | 2026-10-12 08:00\n"
        f"2 | daily 08:00 | {GROUP} | /dailypost | 2026-10-12 08:00\n"
    )
    keeper = Timekeeper()
    keeper.read()
    monkeypatch.setattr(notices, "timekeeper", keeper)
    previous = Run(version="0.98.0", started=datetime(2026, 1, 2, 7, 0, tzinfo=UTC))
    run = Run(version="0.99.0", started=STARTED)
    text = await start_text(bot, previous, run, STARTED + timedelta(seconds=14))
    # What it is, then what needs the admins' attention, then how the bot is
    assert text == "\n".join(
        [
            "🟢 **nejomibot 0.99.0 started**",
            "Monday 19 October 08:00 · ready in 14 s",
            "",
            "🔄 Updated from 0.98.0",
            UNCLEAN.format(time="2026-01-02 08:00"),
            "⚠️ timers.txt: 1 unreadable line, ignored and left unchanged",
            "⚠️ Clock: not synchronized",
            "",
            "⏰ 1 timer",
            "👥 Member of 1 group · 0 chats allowed · 1 admin",
            "📷 Photo library: 1 photo",
            "🧠 Bot memory: 70.0 MB",
            "",
            "🔌 signal-cli-rest-api unset, json-rpc mode",
            f"🐍 signalbot {version('signalbot')} · Python {platform.python_version()}",
            "🖥️ Podman on bothost · aarch64",
        ]
    )


@pytest.mark.usefixtures("swedish")
async def test_a_start_s_notice_in_debug_mode(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_DEBUG", "true")
    monkeypatch.setenv("NEJOMIBOT_DEBUG_GROUP", GROUP)
    get_settings.cache_clear()
    run = Run(version="0.99.0", started=STARTED)
    lines = (await start_text(bot, None, run, STARTED)).splitlines()
    assert lines[:4] == [
        "🟢 **nejomibot 0.99.0 startad**",
        "Måndag 19 Oktober 08:00 · redo efter 0 s",
        "",
        f"🐞 Felsökningsläge: kommunicerar endast med {GROUP}",
    ]


@pytest.mark.parametrize(
    ("previous", "told", "delay"),
    [
        # A first start, or debug mode, or the admins never told
        (None, None, timedelta()),
        # Told 3 minutes ago: the rest of QUIET
        (
            Run(version="0.99.0", started=STARTED),
            NOW - timedelta(minutes=3),
            timedelta(minutes=7),
        ),
        (Run(version="0.99.0", started=STARTED), NOW - QUIET, timedelta()),
        # An update tells at once
        (Run(version="0.98.0", started=STARTED), NOW, timedelta()),
        # QUIET at most, should the clock have been set back since
        (Run(version="0.99.0", started=STARTED), NOW + timedelta(hours=5), QUIET),
    ],
)
def test_a_start_is_told_once_in_quiet_at_most(
    previous: Run | None, told: datetime | None, delay: timedelta
) -> None:
    keeper = Notices()
    keeper.previous = previous
    keeper.run = Run(version="0.99.0", started=NOW, told=told)
    assert keeper.delay(NOW) == delay


async def test_telling_of_a_start(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, SendMessage]] = []

    async def send(bot: SignalBot, recipient: str, message: SendMessage) -> Outcome:
        sent.append((recipient, message))
        return Outcome.SENT

    monkeypatch.setattr(notices, "send", send)
    keeper = Notices()
    keeper.start(bot)
    await keeper.tell_of_start(bot, datetime.now(UTC))
    [(recipient, message)] = sent
    assert recipient == ADMIN
    assert message.text_mode == TextMode.STYLED
    started = f"🟢 **nejomibot {version('nejomibot')} started**"
    assert (message.text or "").startswith(started)
    # Kept, so the next start knows when the admins last heard of one
    run = read_run()
    assert run is not None and run.told is not None
    again = Notices()
    again.start(bot)
    assert again.run is not None and again.run.told == run.told
    assert again.delay(datetime.now(UTC)) > QUIET - timedelta(minutes=1)


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
            "🔐 The safety number for Bob Berg has changed. This usually means a "
            "new phone or a reinstall, but it may also mean that someone else is "
            "using the account. Messages to Bob Berg cannot be sent until the new "
            "safety number is trusted: compare it with the one on their phone "
            "using /contacts Bob Berg, then confirm it with /trust.",
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
            "⚠️ Signal is rate-limiting the bot. Outgoing messages wait: the bot "
            "tries one again after 2 min, then less and less often, every 30 min "
            "at most, and sends the rest once one goes out. To lift the limit, "
            "run signal-account.sh rate-limit --to <your number> on the server "
            "and solve the captcha, then send the bot any command: it tries "
            "again at once.",
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
    await asyncio.gather(*keeper.tasks)
    # The start, then the safety numbers changed since, of which there are none
    [(admin, text)] = told
    assert admin == ADMIN
    assert text.startswith("🟢 **nejomibot 0.98.0 started**")
    assert "\n🔄 Updated from 0.97.0\n" in text
    job = cast(Any, bot.scheduler.get_job("notices-safety-numbers"))  # pyright: ignore[reportUnknownMemberType]
    assert job is not None
    assert str(job.trigger) == "interval[0:05:00]"
