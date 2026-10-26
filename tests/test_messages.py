import asyncio
import itertools
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from helpers import ALICE, GROUP, FakeApi
from signalbot import (
    Config,
    ConnectionMode,
    InMemoryConfig,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import messages
from nejomibot.config import get_settings
from nejomibot.messages import (
    Outbox,
    Outcome,
    PerChat,
    Posted,
    Sent,
    for_chat,
    post_message,
    retry_delays,
)


class FakePost:
    """Answers with the given outcomes in turn, then SENT; records whom it
    was asked to send to, and what it sent, and to whom. Sent ones get the
    time as their timestamp, as from signal-cli."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.tried: list[str] = []
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, recipient: str, message: SendMessage) -> Posted:
        self.tried.append(recipient)
        outcome = self.outcomes.pop(0) if self.outcomes else Outcome.SENT
        if outcome is not Outcome.SENT:
            return Posted(outcome)
        self.sent.append((recipient, message.text or ""))
        return Posted(outcome, int(time.time() * 1000) + len(self.sent))

    def texts(self) -> list[str]:
        return [text for _recipient, text in self.sent]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


type NewOutbox = Callable[..., Outbox]


@pytest.fixture
async def new_outbox() -> AsyncIterator[NewOutbox]:
    """Makes outboxes that stop retrying when the test ends."""
    outboxes: list[Outbox] = []

    def new(*args: Any) -> Outbox:
        outboxes.append(Outbox(*args))
        return outboxes[-1]

    yield new
    for outbox in outboxes:
        if task := outbox._retrying:  # pyright: ignore[reportPrivateUsage]
            task.cancel()


def text(value: str) -> SendMessage:
    return SendMessage(text=value)


# Sending through signalbot


def status(code: int, body: Any) -> Callable[[web.Request], Any]:
    async def answer(request: web.Request) -> web.Response:
        return web.json_response(body, status=code)

    return answer


async def test_sent(bot: SignalBot, signal_api: FakeApi) -> None:
    posted = await post_message(bot, ALICE, text("hej"))
    assert posted == Posted(Outcome.SENT, signal_api.timestamp)
    [sent] = signal_api.bodies("POST", "/v2/send")
    assert (sent["message"], sent["recipients"]) == ("hej", [ALICE])


async def test_sent_to_a_group(bot: SignalBot, signal_api: FakeApi) -> None:
    assert (await post_message(bot, GROUP, text("hej"))).outcome is Outcome.SENT
    assert signal_api.bodies("POST", "/v2/send")[0]["recipients"] == [GROUP]


async def test_a_send_that_reached_some_is_sent(
    bot: SignalBot, signal_api: FakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    errors = {"recipients": [{"number": ALICE, "reason": "NETWORK"}]}
    signal_api.route(
        "POST", "/v2/send", status(201, [{"timestamp": "1", "errors": errors}])
    )
    assert await post_message(bot, GROUP, text("hej")) == Posted(Outcome.SENT, 1)
    assert f"not delivered to {ALICE}: NETWORK" in caplog.text


@pytest.mark.parametrize(
    ("code", "error", "outcome"),
    [
        # signal-cli sent it to nobody, e.g. without internet
        (400, "Failed to send message: timeout (IOException)", Outcome.NOT_SENT),
        (
            400,
            "Unable to complete request due to untrusted recipient keys",
            Outcome.NOT_SENT,
        ),
        (429, "Failed to send message due to rate limiting", Outcome.RATE_LIMITED),
    ],
)
async def test_an_error_answer_is_not_sent(
    bot: SignalBot, signal_api: FakeApi, code: int, error: str, outcome: Outcome
) -> None:
    signal_api.route("POST", "/v2/send", status(code, {"error": error}))
    assert await post_message(bot, ALICE, text("hej")) == Posted(outcome)
    assert outcome.waits


async def test_rate_limit_says_how_to_lift_it(
    bot: SignalBot, signal_api: FakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    signal_api.route("POST", "/v2/send", status(429, {"error": "rate limiting"}))
    await post_message(bot, ALICE, text("hej"))
    assert "nejomibot-account rate-limit" in caplog.text


async def test_not_sent_when_the_api_is_down() -> None:
    bot = SignalBot(
        Config(
            signal_service="127.0.0.1:1",
            phone_number="+46700000000",
            connection_mode=ConnectionMode.HTTP_ONLY,
            storage=InMemoryConfig(),
        )
    )
    handlers = list(logging.getLogger("signalbot").handlers)
    try:
        assert await post_message(bot, ALICE, text("hej")) == Posted(Outcome.NOT_SENT)
    finally:
        await bot.close()
        logging.getLogger("signalbot").handlers = handlers


async def test_a_timeout_is_not_retried(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # It may have arrived, and a retry would post it twice
    async def slow(request: web.Request) -> web.Response:
        await asyncio.sleep(1)
        return web.json_response([{"timestamp": "1"}], status=201)

    monkeypatch.setattr(messages, "SEND_TIMEOUT", 0.05)
    signal_api.route("POST", "/v2/send", slow)
    assert await post_message(bot, ALICE, text("hej")) == Posted(Outcome.GIVE_UP)


async def test_a_dropped_connection_is_not_retried(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    async def hang_up(request: web.Request) -> web.Response:
        assert request.transport is not None
        request.transport.close()
        return web.Response(status=201)

    signal_api.route("POST", "/v2/send", hang_up)
    assert await post_message(bot, ALICE, text("hej")) == Posted(Outcome.GIVE_UP)


async def test_a_group_the_bot_isnt_in_is_given_up(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    gone = "group.Z29uZQ=="
    assert await post_message(bot, gone, text("hej")) == Posted(Outcome.GIVE_UP)
    assert signal_api.bodies("POST", "/v2/send") == []


# The outbox


async def test_sends_right_away(new_outbox: NewOutbox) -> None:
    post = FakePost()
    outbox = new_outbox(post)
    assert await outbox.send(GROUP, text("hej")) is Outcome.SENT
    assert post.sent == [(GROUP, "hej")]
    assert len(outbox) == 0
    assert outbox.oldest() is None


async def test_send_says_what_became_of_it(new_outbox: NewOutbox) -> None:
    post = FakePost(Outcome.GIVE_UP, Outcome.NOT_SENT, Outcome.NOT_SENT)
    outbox = new_outbox(post, Clock())
    assert await outbox.send(GROUP, text("lost")) is Outcome.GIVE_UP
    assert await outbox.send(GROUP, text("waits")) is Outcome.NOT_SENT
    # Behind the one waiting, which is tried first and still waits
    assert await outbox.send(GROUP, text("waits too")) is Outcome.NOT_SENT
    assert len(outbox) == 2


async def test_unstarted_outbox_says_so() -> None:
    with pytest.raises(RuntimeError, match="isn't started"):
        await Outbox().send(GROUP, text("hej"))


async def test_sent_messages_are_logged(new_outbox: NewOutbox) -> None:
    outbox = new_outbox(FakePost(Outcome.GIVE_UP))
    await outbox.send(GROUP, text("rejected"))
    await outbox.send(GROUP, text("one"))
    await outbox.send(ALICE, text("other chat"))
    await outbox.send(GROUP, text("two"))

    latest, before = outbox.sent.pop({GROUP}), outbox.sent.pop({GROUP})
    assert isinstance(latest, Sent) and isinstance(before, Sent)
    assert latest.chat == before.chat == GROUP
    assert latest.timestamp > before.timestamp
    assert outbox.sent.pop({GROUP}) is None  # the rejected one wasn't sent
    assert outbox.sent.pop({ALICE})


@pytest.mark.usefixtures("swedish")
async def test_not_sent_is_retried_with_delay_note(new_outbox: NewOutbox) -> None:
    clock = Clock()
    post = FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT)
    outbox = new_outbox(post, clock)
    await outbox.send(GROUP, text("hej"))
    assert len(outbox) == 1
    assert outbox.oldest() == clock.now

    await outbox.flush()  # still down
    assert len(outbox) == 1
    await outbox.flush()
    assert len(outbox) == 0
    assert post.texts() == [
        "hej\n\n⏳ Försenat: meddelandet skulle ha skickats kl. 08:00"
    ]


async def test_give_up_is_not_retried(new_outbox: NewOutbox) -> None:
    post = FakePost(Outcome.GIVE_UP)
    outbox = new_outbox(post)
    await outbox.send(GROUP, text("hej"))
    assert len(outbox) == 0
    assert post.sent == []


async def test_keeps_order_per_recipient(new_outbox: NewOutbox) -> None:
    post = FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT)
    outbox = new_outbox(post, Clock())
    await outbox.send(GROUP, text("weather"))
    await outbox.send(GROUP, text("photo"))  # weather is tried first: still down
    await outbox.send(ALICE, text("other chat"))
    assert post.texts() == ["other chat"]

    await outbox.flush()
    assert [t.split("\n")[0] for t in post.texts()] == [
        "other chat",
        "weather",
        "photo",
    ]


@pytest.mark.usefixtures("swedish")
async def test_a_new_message_sends_the_waiting_ones_first(
    new_outbox: NewOutbox,
) -> None:
    post = FakePost(Outcome.NOT_SENT)
    outbox = new_outbox(post, Clock())
    await outbox.send(GROUP, text("status"))  # Signal is down
    await outbox.send(GROUP, text("help"))  # and back: no wait for the next round
    assert len(outbox) == 0
    assert post.texts() == [
        "status\n\n⏳ Försenat: meddelandet skulle ha skickats kl. 08:00",
        "help",
    ]


@pytest.mark.usefixtures("swedish")
async def test_old_messages_are_dropped_and_reported(new_outbox: NewOutbox) -> None:
    clock = Clock()
    post = FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT)
    outbox = new_outbox(post, clock)
    await outbox.send(GROUP, text("one"))
    await outbox.send(GROUP, text("two"))  # one is tried first: still down

    clock.now += timedelta(hours=3, minutes=1)
    await outbox.send(GROUP, text("three"))
    assert len(outbox) == 0
    assert post.texts() == [
        "three",
        "Något gick fel: 2 meddelanden kunde inte levereras inom 3 timmar och har "
        "kasserats",
    ]


async def test_what_the_outbox_loses_is_counted(new_outbox: NewOutbox) -> None:
    # For the health checks: sends it gave up on, and messages it dropped
    clock = Clock()
    outbox = new_outbox(FakePost(Outcome.GIVE_UP, Outcome.NOT_SENT), clock)
    await outbox.send(GROUP, text("timed out"))
    await outbox.send(ALICE, text("waits"))
    assert (outbox.given_up, outbox.discarded) == (1, 0)

    clock.now += timedelta(hours=3, minutes=1)
    await outbox.flush()
    assert len(outbox) == 0
    assert (outbox.given_up, outbox.discarded) == (1, 1)


def test_retries_come_soon_then_less_often() -> None:
    delays = [d.total_seconds() for d in itertools.islice(retry_delays(), 6)]
    assert delays == [10, 20, 40, 80, 120, 120]


async def test_retry_loop_sends_and_stops(
    monkeypatch: pytest.MonkeyPatch, new_outbox: NewOutbox
) -> None:
    monkeypatch.setattr(messages, "FIRST_RETRY", timedelta(milliseconds=10))
    post = FakePost(Outcome.NOT_SENT)
    outbox = new_outbox(post)
    await outbox.send(GROUP, text("hej"))
    retrying = outbox._retrying  # pyright: ignore[reportPrivateUsage]
    assert retrying is not None
    await asyncio.wait_for(retrying, 1)
    assert len(outbox) == 0
    assert len(post.sent) == 1
    assert outbox._retrying is None  # pyright: ignore[reportPrivateUsage]


async def test_started_outbox_sends_through_the_bot(
    bot: SignalBot, signal_api: FakeApi, new_outbox: NewOutbox
) -> None:
    outbox = new_outbox()
    outbox.start(bot)
    await outbox.send(ALICE, text("hej"))
    assert outbox.sent.pop({ALICE}) == Sent(signal_api.timestamp, ALICE)


async def test_while_rate_limited_one_is_tried_at_a_time(
    monkeypatch: pytest.MonkeyPatch, new_outbox: NewOutbox
) -> None:
    # Trying while Signal rate-limits the bot only meets the limit, and can
    # keep it in place: new messages wait, and the oldest is tried alone, less
    # and less often
    monkeypatch.setattr(messages, "RATE_LIMITED_FIRST", timedelta(milliseconds=20))
    clock = Clock()
    post = FakePost(Outcome.RATE_LIMITED, Outcome.RATE_LIMITED)
    outbox = new_outbox(post, clock)
    assert await outbox.send(GROUP, text("one")) is Outcome.RATE_LIMITED
    clock.now += timedelta(seconds=1)
    assert await outbox.send(ALICE, text("two")) is Outcome.RATE_LIMITED
    assert await outbox.send(GROUP, text("three")) is Outcome.RATE_LIMITED
    assert post.tried == [GROUP]  # the new ones wait, untried
    retrying = outbox._retrying  # pyright: ignore[reportPrivateUsage]
    assert retrying is not None
    # The first try meets the limit, the second goes out: the rest follow,
    # each chat's in order
    await asyncio.wait_for(retrying, 1)
    assert post.tried == [GROUP, GROUP, GROUP, GROUP, ALICE]
    assert [t.split("\n")[0] for t in post.texts()] == ["one", "three", "two"]
    assert len(outbox) == 0
    assert not outbox.rate_limited


def test_tries_while_rate_limited_come_less_and_less_often(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEJOMIBOT_RATE_LIMIT_RETRY_MINUTES", "20")
    get_settings.cache_clear()
    delays = itertools.islice(messages.rate_limited_delays(), 6)
    assert [d.total_seconds() / 60 for d in delays] == [2, 4, 8, 16, 20, 20]


async def test_a_round_of_retries_stops_at_a_rate_limit(new_outbox: NewOutbox) -> None:
    # The other chats' would meet the limit too
    post = FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT, Outcome.RATE_LIMITED)
    outbox = new_outbox(post, Clock())
    await outbox.send(GROUP, text("one"))
    await outbox.send(ALICE, text("two"))
    await outbox.flush()
    assert post.tried == [GROUP, ALICE, GROUP]
    assert outbox.rate_limited
    assert len(outbox) == 2


async def test_an_admins_command_has_it_try_again_at_once(
    monkeypatch: pytest.MonkeyPatch, new_outbox: NewOutbox
) -> None:
    # An admin who has just lifted the limit needn't wait for the next try,
    # but tries come a minute apart at the soonest
    post = FakePost(Outcome.RATE_LIMITED)
    outbox = new_outbox(post, Clock())
    await outbox.send(GROUP, text("one"))
    outbox.nudge()
    await asyncio.sleep(0.05)
    assert post.tried == [GROUP]
    monkeypatch.setattr(messages, "NUDGE_AFTER", timedelta())
    outbox.nudge()
    retrying = outbox._retrying  # pyright: ignore[reportPrivateUsage]
    assert retrying is not None
    await asyncio.wait_for(retrying, 1)
    assert post.tried == [GROUP, GROUP]
    assert not outbox.rate_limited
    # Without a limit, a nudge does nothing
    outbox.nudge()
    assert outbox._retrying is None  # pyright: ignore[reportPrivateUsage]


def kept_files() -> list[Path]:
    return sorted(get_settings().outbox_dir.glob("*.json"))


async def test_a_waiting_message_is_kept_on_disk(
    monkeypatch: pytest.MonkeyPatch, new_outbox: NewOutbox
) -> None:
    monkeypatch.setattr(messages, "KEEP_AFTER", timedelta(milliseconds=10))
    post = FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT)
    outbox = new_outbox(post, Clock())
    await outbox.send(GROUP, text("hej"))
    assert kept_files() == []  # not yet: it may go out in a moment
    await asyncio.sleep(0.05)
    [path] = kept_files()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == {
        "recipient": GROUP,
        "queued_at": "2026-10-11T06:00:00Z",
        "message": {"text": "hej"},
    }
    await outbox.flush()  # still down
    assert kept_files() == [path]
    await outbox.flush()
    assert kept_files() == []


async def test_a_message_sent_soon_is_never_written(
    monkeypatch: pytest.MonkeyPatch, new_outbox: NewOutbox
) -> None:
    monkeypatch.setattr(messages, "KEEP_AFTER", timedelta(milliseconds=10))
    outbox = new_outbox(FakePost(Outcome.NOT_SENT), Clock())
    await outbox.send(GROUP, text("hej"))
    await outbox.flush()
    await asyncio.sleep(0.05)
    assert not get_settings().outbox_dir.exists()


@pytest.mark.usefixtures("swedish")
async def test_waiting_messages_outlast_a_restart(new_outbox: NewOutbox) -> None:
    clock = Clock()
    before = new_outbox(FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT), clock)
    await before.send(GROUP, text("one"))
    await before.send(GROUP, text("two"))
    await before.send(ALICE, text("other chat"))
    before.keep_all()  # as the bot stops
    assert len(kept_files()) == 2
    (get_settings().outbox_dir / "broken.json").write_text("{")

    post = FakePost()
    after = new_outbox(post, clock)
    after.load()
    assert len(after) == 2
    assert after.oldest() == clock.now
    await after.flush()
    assert post.texts() == [
        "one\n\n⏳ Försenat: meddelandet skulle ha skickats kl. 08:00",
        "two\n\n⏳ Försenat: meddelandet skulle ha skickats kl. 08:00",
    ]
    # What can't be read is left alone
    assert [path.name for path in kept_files()] == ["broken.json"]


async def test_the_log_says_where_to_not_who(
    new_outbox: NewOutbox, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, "nejomibot")
    outbox = new_outbox(FakePost(Outcome.NOT_SENT), Clock())
    await outbox.send(ALICE, text("hej"))
    await outbox.flush()
    assert "Queued a message to a contact, 1 waiting" in caplog.text
    assert ALICE not in caplog.text


# Messages some chats get with a text of their own


def test_a_message_per_chat() -> None:
    message = PerChat(
        text="for all",
        texts={GROUP: "for the group"},
        text_mode=TextMode.STYLED,
        base64_attachments=["aGVq"],
    )
    # As it goes to signalbot: a message like any other, as the chat gets it
    assert for_chat(message, GROUP) == SendMessage(
        text="for the group", text_mode=TextMode.STYLED, base64_attachments=["aGVq"]
    )
    assert type(for_chat(message, ALICE)) is SendMessage
    assert for_chat(message, ALICE).text == "for all"
    plain = text("hej")
    assert for_chat(plain, GROUP) is plain


async def test_each_chat_gets_its_own(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = FakePost()
    monkeypatch.setattr(messages, "outbox", Outbox(post))
    message = PerChat(text="for all", texts={GROUP: "for the group"})
    for chat in (GROUP, ALICE):
        await messages.send(bot, chat, message)
    assert post.sent == [(GROUP, "for the group"), (ALICE, "for all")]


async def test_a_chat_with_nothing_to_get_gets_nothing(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = FakePost()
    monkeypatch.setattr(messages, "outbox", Outbox(post))
    # As /today's in a post, on a day with nothing but a birthday in the group
    message = PerChat(text="", texts={GROUP: "🎂 Alice"})
    for chat in (GROUP, ALICE):
        assert await messages.send(bot, chat, message) is Outcome.SENT
    assert post.sent == [(GROUP, "🎂 Alice")]


# Sending once, and saying when Signal starts rate-limiting the bot


async def test_tried_once(new_outbox: NewOutbox) -> None:
    outbox = new_outbox(FakePost(Outcome.NOT_SENT))
    assert await outbox.try_once(ALICE, text("now or never")) is Outcome.NOT_SENT
    assert len(outbox) == 0
    assert await outbox.try_once(ALICE, text("now")) is Outcome.SENT


async def test_says_when_signal_starts_rate_limiting(new_outbox: NewOutbox) -> None:
    post = FakePost(Outcome.RATE_LIMITED, Outcome.RATE_LIMITED)
    outbox = new_outbox(post)
    started: list[bool] = []
    outbox.on_rate_limited = lambda: started.append(True)
    await outbox.send(ALICE, text("one"))
    await outbox.try_once(GROUP, text("two"))
    # Once, as it starts
    assert started == [True]
    assert outbox.rate_limited
    # Gone out, it's lifted
    await outbox.probe()
    assert not outbox.rate_limited
    assert post.tried == [ALICE, GROUP, ALICE]


def test_the_delay_note_shows_as_it_is_in_a_styled_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def translated(message: str) -> str:
        """As a translation with a mark in it would have it."""
        return "⏳ *Late*: due at {time}"

    monkeypatch.setattr(messages, "_", translated)
    queued_at = Clock().now
    styled = SendMessage(text="**Hej**", text_mode=TextMode.STYLED)
    assert messages.delayed(styled, queued_at).text == (
        "**Hej**\n\n⏳ \\*Late\\*: due at 08:00"
    )
    assert messages.delayed(text("Hej"), queued_at).text == (
        "Hej\n\n⏳ *Late*: due at 08:00"
    )


async def test_the_delay_note_is_in_the_chats_language(new_outbox: NewOutbox) -> None:
    get_settings().data_file("languages.txt").write_text(f"{GROUP} | sv\n")
    post = FakePost(Outcome.NOT_SENT, Outcome.NOT_SENT)
    outbox = new_outbox(post, Clock())
    await outbox.send(GROUP, text("hej"))
    await outbox.send(ALICE, text("hi"))
    await outbox.flush()
    assert post.texts() == [
        "hej\n\n⏳ Försenat: meddelandet skulle ha skickats kl. 08:00",
        "hi\n\n⏳ Delayed: this message was due at 08:00",
    ]
