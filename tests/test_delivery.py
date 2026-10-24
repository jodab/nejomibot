import asyncio
import contextlib
import itertools
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web
from helpers import (
    ALICE,
    ALICE_ID,
    BOB_ID,
    CAROL_ID,
    GROUP,
    ME,
    NOW_MS,
    FakeApi,
    message_from,
)
from signalbot import DataMessageContext, SendMessage, SignalBot, TextMode

from nejomibot import delivery
from nejomibot.config import get_settings
from nejomibot.delivery import (
    CHECK_AFTER,
    Delivery,
    Receipts,
    confirm,
    delivery_text,
    expected,
    receipt_in,
    status_text,
)
from nejomibot.messages import Outbox, Outcome, Posted, Sent, SentLog

RECEIVE = f"/v1/receive/{ME}"
MINUTE_MS = 60 * 1000
# Something else signal-cli-rest-api passes on: a message to the bot
DATA_MESSAGE = json.dumps(
    {
        "envelope": {
            "sourceUuid": ALICE_ID,
            "timestamp": NOW_MS,
            "dataMessage": {"timestamp": NOW_MS, "message": "/ping"},
        },
        "account": ME,
    }
)


def receipt(
    who: str, *timestamps: int, read: bool = False, viewed: bool = False
) -> str:
    """A receipt for the messages sent at the timestamps, as
    signal-cli-rest-api passes it on in json-rpc mode."""
    return json.dumps(
        {
            "envelope": {
                "source": who,
                "sourceNumber": None,
                "sourceUuid": who,
                "sourceName": "",
                "sourceDevice": 1,
                "timestamp": NOW_MS + 5000,
                "serverReceivedTimestamp": NOW_MS + 5100,
                "serverDeliveredTimestamp": NOW_MS + 5200,
                "receiptMessage": {
                    "when": NOW_MS + 5000,
                    "isDelivery": not (read or viewed),
                    "isRead": read,
                    "isViewed": viewed,
                    "timestamps": list(timestamps),
                },
            },
            "account": ME,
        }
    )


def log_of(*sent: Sent) -> SentLog:
    log = SentLog()
    for each in sent:
        log.add(each)
    return log


def confirm_all(log: SentLog, *receipts: str) -> None:
    for data in receipts:
        envelope = receipt_in(data)
        assert envelope is not None
        confirm(log, envelope)


async def ready() -> None:
    pass


# Receipts


def test_a_receipt_is_read_as_signal_cli_rest_api_passes_it_on() -> None:
    envelope = receipt_in(receipt(ALICE_ID, 1, 2, read=True))
    assert envelope is not None
    assert envelope.source_uuid == ALICE_ID
    assert envelope.receipt_message is not None
    assert envelope.receipt_message.is_read
    assert envelope.receipt_message.timestamps == [1, 2]


def test_what_isnt_a_receipt_is_let_be() -> None:
    assert receipt_in(DATA_MESSAGE) is None
    # Nor what only names one, or can't be read
    named = {"envelope": {"dataMessage": {"message": '"receiptMessage"'}}}
    assert receipt_in(json.dumps(named)) is None
    assert receipt_in('{"receiptMessage": ') is None


def test_receipts_say_who_got_and_read_each_message() -> None:
    first, second = Sent(NOW_MS, GROUP), Sent(NOW_MS + 1, GROUP)
    log = log_of(first, second)
    confirm_all(
        log,
        receipt(ALICE_ID, NOW_MS, NOW_MS + 1),
        receipt(ALICE_ID, NOW_MS, read=True),
        receipt(CAROL_ID, NOW_MS + 1, viewed=True),
        # From another of Alice's devices, later: read still
        receipt(ALICE_ID, NOW_MS),
        # For a message the bot doesn't know, as one from before its start
        receipt(BOB_ID, NOW_MS - 1),
    )
    assert first.confirmed == {ALICE_ID: True}
    assert second.confirmed == {ALICE_ID: False, CAROL_ID: True}


def test_the_sent_log_finds_a_message_by_its_timestamp() -> None:
    log = log_of(Sent(NOW_MS, GROUP), Sent(NOW_MS + 2, ALICE))
    assert log.find(NOW_MS + 2) == Sent(NOW_MS + 2, ALICE)
    assert log.find(NOW_MS) == Sent(NOW_MS, GROUP)
    assert log.find(NOW_MS + 1) is None
    assert log.find(NOW_MS + 3) is None


async def test_the_outbox_tells_of_each_message_sent() -> None:
    async def post(recipient: str, message: SendMessage) -> Posted:
        return Posted(Outcome.SENT, NOW_MS)

    outbox = Outbox(post)
    told: list[Sent] = []
    outbox.on_sent = told.append
    assert await outbox.send(GROUP, SendMessage(text="hej")) is Outcome.SENT
    assert told == [Sent(NOW_MS, GROUP)]
    assert outbox.sent.find(NOW_MS) is told[0]


# How many got it


async def test_who_should_confirm(bot: SignalBot) -> None:
    # Familjen's members but the bot: Alice and Carol
    assert expected(bot, GROUP) == 2
    assert expected(bot, ALICE) == 1
    # A group the bot has left, and one it was never in
    assert expected(bot, "group.b2xk") is None
    assert expected(bot, "group.bm9uZQ==") is None


def test_what_a_messages_status_says() -> None:
    sent = Sent(NOW_MS, GROUP)
    soon, later = sent.at + timedelta(minutes=1), sent.at + CHECK_AFTER
    assert status_text(sent, 2, soon) == "⏳ 0/2"
    assert status_text(sent, 2, later) == "⚠️ 0/2"
    # A group with nobody else in it
    assert status_text(sent, 0, later) == "📬 0/0"
    sent.confirmed[ALICE_ID] = False
    assert status_text(sent, 2, later) == "📬 1/2"
    sent.confirmed[CAROL_ID] = True
    assert status_text(sent, 2, later) == "📬 2/2 · 👀 1"
    # In a group the bot isn't in
    assert status_text(sent, None, later) == "📬 2 · 👀 1"


# /delivery


@pytest.fixture
def listening(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot has heard the receipts for the last hour."""
    since = datetime.now(UTC) - timedelta(hours=1)
    monkeypatch.setattr(delivery.receipts, "since", since)


@pytest.mark.usefixtures("listening")
async def test_delivery_shows_the_latest_and_how_many_got_them(bot: SignalBot) -> None:
    weather = Sent(NOW_MS - 20 * MINUTE_MS, GROUP, "Weather in Stockholm")
    pong = Sent(NOW_MS, ALICE, "pong!")
    pong.confirmed[ALICE_ID] = True
    lines = (await delivery_text(bot, log_of(weather, pong))).splitlines()
    assert lines[0] == "📬 **Delivery of the bot's latest messages, newest first:**"
    assert lines[1].endswith(f" · 👤 Alice ({ALICE}) · pong! · 📬 1/1 · 👀 1")
    assert lines[2].endswith(" · 👥 Familjen · Weather in Stockholm · ⚠️ 0/2")
    assert lines[3:] == [
        "",
        "📬 delivered, of those in the chat · 👀 read · ⏳ none yet · "
        "⚠️ none within 10 minutes",
    ]


@pytest.mark.usefixtures("listening")
async def test_delivery_shows_delivery_messages(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_DELIVERY_MESSAGES", "1")
    get_settings.cache_clear()
    log = log_of(Sent(NOW_MS - 1, GROUP, "first"), Sent(NOW_MS, ALICE, "second"))
    lines = (await delivery_text(bot, log)).splitlines()
    assert len(lines) == 4
    assert " · second · " in lines[1]


async def test_delivery_says_when_receipts_arent_heard(bot: SignalBot) -> None:
    lines = (await delivery_text(bot, log_of(Sent(NOW_MS, ALICE)))).splitlines()
    assert lines[-2] == (
        "⚠️ Delivery receipts are not being received at the moment: the counts may "
        "be behind."
    )


async def test_delivery_when_the_bot_has_sent_nothing(bot: SignalBot) -> None:
    started = datetime.now(UTC) - timedelta(hours=2)
    text = await delivery_text(bot, SentLog(lambda: started))
    tz = get_settings().tz
    assert text == (
        "No messages sent since the bot started, at "
        f"{started.astimezone(tz):%Y-%m-%d %H:%M}."
    )
    long_ago = datetime.now(UTC) - timedelta(days=2)
    text = await delivery_text(bot, SentLog(lambda: long_ago))
    assert text == "No messages sent in the last 24 hours."


@pytest.mark.usefixtures("swedish", "listening", "answers")
async def test_delivery_in_swedish(
    bot: SignalBot,
    monkeypatch: pytest.MonkeyPatch,
    answers: list[SendMessage],
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ALICE}"]')
    get_settings.cache_clear()
    monkeypatch.setattr(delivery.outbox, "sent", log_of(Sent(NOW_MS, GROUP, "Hej")))
    context = DataMessageContext(bot, message_from(ALICE, "/leverans"))
    await Delivery().handle_data_message(context)
    [reply] = answers
    assert reply.text_mode == TextMode.STYLED
    lines = (reply.text or "").splitlines()
    assert lines[0] == "📬 **Leverans av botens senaste meddelanden, nyaste först:**"
    assert lines[1].endswith(" · 👥 Familjen · Hej · ⏳ 0/2")
    assert lines[-1] == (
        "📬 levererat, av dem i chatten · 👀 läst · ⏳ ingen ännu · "
        "⚠️ ingen inom 10 minuter"
    )


# The check after 10 minutes


def logged(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(record.levelno, record.getMessage()) for record in caplog.records]


async def test_a_message_nobody_confirmed_is_a_warning(
    bot: SignalBot, caplog: pytest.LogCaptureFixture
) -> None:
    keeper = Receipts()
    sent = Sent(NOW_MS, GROUP)
    keeper.since = sent.at - timedelta(seconds=1)
    with caplog.at_level(logging.DEBUG, logger="nejomibot.delivery"):
        keeper.check(bot, sent)
        sent.confirmed[ALICE_ID] = True
        keeper.check(bot, sent)
    assert logged(caplog) == [
        (
            logging.WARNING,
            f"Message {NOW_MS} to a group: nobody's phone confirmed it in 10 "
            "minutes. Signal took it, but it may not have arrived",
        ),
        (
            logging.DEBUG,
            f"Message {NOW_MS} to {GROUP}: 1 of 2 got it in 10 minutes, 1 read it",
        ),
    ]


async def test_a_message_isnt_checked_without_all_its_receipts(
    bot: SignalBot, caplog: pytest.LogCaptureFixture
) -> None:
    keeper = Receipts()
    sent = Sent(NOW_MS, GROUP)
    with caplog.at_level(logging.DEBUG, logger="nejomibot.delivery"):
        keeper.check(bot, sent)  # not hearing them at all
        keeper.since = sent.at + timedelta(seconds=1)  # only since after it
        keeper.check(bot, sent)
    unheard = f"Message {NOW_MS}: some receipts unheard, not checked"
    assert logged(caplog) == [(logging.DEBUG, unheard)] * 2


async def test_each_message_sent_is_checked_later(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(delivery.outbox, "on_sent", None)
    monkeypatch.setattr(delivery, "CHECK_AFTER", timedelta(0))
    keeper = Receipts()
    checked: list[Sent] = []

    def check(bot: SignalBot, sent: Sent) -> None:
        checked.append(sent)

    monkeypatch.setattr(keeper, "check", check)
    keeper.start(bot)
    assert bot.scheduler.get_job("delivery-receipts") is not None  # pyright: ignore[reportUnknownMemberType]
    on_sent = delivery.outbox.on_sent
    assert on_sent is not None
    sent = Sent(NOW_MS, GROUP)
    on_sent(sent)
    await asyncio.sleep(0.01)
    assert checked == [sent]


async def test_hearing_isn_t_the_scheduler_s_job(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Which logs its cancelling at shutdown as an error
    keeper = Receipts()

    async def listen(bot: SignalBot, log: SentLog) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(keeper, "listen", listen)
    async with asyncio.timeout(1):
        await keeper.hear(bot)
    assert keeper.hearing is not None
    assert not keeper.hearing.done()
    keeper.hearing.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await keeper.hearing


# Hearing them


@pytest.fixture
def at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot connects again at once, rather than after 10 s and more."""
    monkeypatch.setattr(delivery, "retry_delays", lambda: itertools.repeat(timedelta()))


async def heard(
    monkeypatch: pytest.MonkeyPatch,
    bot: SignalBot,
    sent: Sent,
    everyone: set[str],
) -> None:
    """Listen until everyone's receipt for the message is in, then stop."""
    keeper, done = Receipts(), asyncio.Event()

    def confirmed(log: SentLog, envelope: delivery.Envelope) -> None:
        confirm(log, envelope)
        if set(sent.confirmed) == everyone:
            done.set()

    monkeypatch.setattr(delivery, "confirm", confirmed)
    task = asyncio.create_task(keeper.listen(bot, log_of(sent)))
    try:
        async with asyncio.timeout(5):
            await done.wait()
        assert keeper.since is not None
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert keeper.since is None


async def stay_open(websocket: web.WebSocketResponse) -> None:
    """Until the bot closes the connection."""
    async for _message in websocket:
        pass


@pytest.mark.usefixtures("at_once")
async def test_receipts_are_heard_again_after_the_connection_ends(
    bot: SignalBot,
    signal_api: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(bot, "wait_until_ready", ready)
    connections = 0

    async def receive(request: web.Request) -> web.StreamResponse:
        nonlocal connections
        connections += 1
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        if connections == 1:
            await websocket.send_str(DATA_MESSAGE)
            await websocket.send_str(receipt(ALICE_ID, NOW_MS))
            await websocket.close()
        else:
            await websocket.send_str(receipt(CAROL_ID, NOW_MS, read=True))
            await stay_open(websocket)
        return websocket

    signal_api.route("GET", RECEIVE, receive)
    sent = Sent(NOW_MS, GROUP)
    with caplog.at_level(logging.INFO, logger="nejomibot.delivery"):
        await heard(monkeypatch, bot, sent, {ALICE_ID, CAROL_ID})
    assert sent.confirmed == {ALICE_ID: False, CAROL_ID: True}
    assert connections == 2
    assert logged(caplog) == [
        (logging.WARNING, "Hearing receipts stopped: the connection ended"),
        (logging.INFO, "Hearing receipts again"),
    ]


@pytest.mark.usefixtures("at_once")
async def test_what_keeps_failing_is_said_once(
    bot: SignalBot,
    signal_api: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(bot, "wait_until_ready", ready)
    attempts = 0

    async def receive(request: web.Request) -> web.StreamResponse:
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            return web.json_response({"error": "not yet"}, status=500)
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        await websocket.send_str(receipt(ALICE_ID, NOW_MS))
        await stay_open(websocket)
        return websocket

    signal_api.route("GET", RECEIVE, receive)
    sent = Sent(NOW_MS, GROUP)
    with caplog.at_level(logging.INFO, logger="nejomibot.delivery"):
        await heard(monkeypatch, bot, sent, {ALICE_ID})
    assert attempts == 4
    assert logged(caplog) == [
        (logging.WARNING, "Hearing receipts failed: 500 Invalid response status"),
        (logging.INFO, "Hearing receipts again"),
    ]
