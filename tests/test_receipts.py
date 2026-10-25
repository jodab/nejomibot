import asyncio
from typing import cast

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, GROUP, ME, FakeApi
from signalbot import DataMessage, DataMessageContext, GroupInfo, SignalBot

from nejomibot import receipts
from nejomibot.messages import Outbox, collected
from nejomibot.receipts import mark_read, show_typing, stop_typing

RECEIPTS = f"/v1/receipts/{ME}"
# As a group message names its group: by the ID signalbot calls internal
GROUP_INTERNAL_ID = "internal-Familjen"


def context(
    bot: SignalBot,
    number: str | None,
    uuid: str | None,
    timestamp: int,
    group: str | None = None,
) -> DataMessageContext:
    message = DataMessage(
        server_delivered_timestamp=timestamp,
        server_received_timestamp=timestamp,
        timestamp=timestamp,
        source_number=number,
        source_uuid=uuid,
        group_info=(
            GroupInfo.model_validate({"groupId": group, "revision": 1})
            if group
            else None
        ),
        text="/ping",
    )
    return DataMessageContext(bot, message)


async def test_mark_read_sends_receipt_to_sender(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    await mark_read(context(bot, ALICE, ALICE_ID, 1791725436929))
    await mark_read(context(bot, ALICE, None, 1791725436930))
    assert signal_api.bodies("POST", RECEIPTS) == [
        {"recipient": ALICE_ID, "timestamp": 1791725436929, "receipt_type": "read"},
        {"recipient": ALICE, "timestamp": 1791725436930, "receipt_type": "read"},
    ]


async def test_mark_read_in_a_group_goes_to_the_sender(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    await mark_read(context(bot, ALICE, ALICE_ID, 1791725436929, GROUP_INTERNAL_ID))
    assert signal_api.bodies("POST", RECEIPTS) == [
        {"recipient": ALICE_ID, "timestamp": 1791725436929, "receipt_type": "read"},
    ]


async def test_mark_read_not_for_a_timer(bot: SignalBot, signal_api: FakeApi) -> None:
    token = collected.set([])
    try:
        await mark_read(context(bot, ALICE, ALICE_ID, 1))
    finally:
        collected.reset(token)
    assert signal_api.requests == []


async def test_neither_while_signal_rate_limits_the_bot(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each is a message, which would only meet the limit
    limited = Outbox()
    limited._rate_limited = True  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(receipts, "outbox", limited)
    await mark_read(context(bot, ALICE, ALICE_ID, 1))
    await show_typing(context(bot, ALICE, ALICE_ID, 1, GROUP_INTERNAL_ID))
    assert signal_api.requests == []


async def test_mark_read_never_raises(bot: SignalBot, signal_api: FakeApi) -> None:
    async def fail(request: web.Request) -> web.Response:
        return web.json_response({"error": "No"}, status=400)

    signal_api.route("POST", RECEIPTS, fail)
    await mark_read(context(bot, ALICE, None, 1))


async def test_show_typing(bot: SignalBot, signal_api: FakeApi) -> None:
    await show_typing(context(bot, ALICE, ALICE_ID, 1, GROUP_INTERNAL_ID))
    assert signal_api.bodies("PUT", f"/v1/typing-indicator/{ME}") == [
        {"recipient": GROUP}
    ]


class TypingContext:
    def __init__(self, delay: float = 0, error: Exception | None = None) -> None:
        self.delay, self.error, self.typed = delay, error, False

    async def start_typing(self) -> None:
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        self.typed = True


async def test_show_typing_never_raises() -> None:
    await show_typing(cast(DataMessageContext, TypingContext(error=OSError("down"))))


async def test_show_typing_gives_up_soon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipts, "TIMEOUT", 0.01)
    typing = TypingContext(delay=10)
    await asyncio.wait_for(show_typing(cast(DataMessageContext, typing)), 1)
    assert not typing.typed


async def test_stop_typing(bot: SignalBot, signal_api: FakeApi) -> None:
    await stop_typing(context(bot, ALICE, ALICE_ID, 1, GROUP_INTERNAL_ID))
    assert signal_api.bodies("DELETE", f"/v1/typing-indicator/{ME}") == [
        {"recipient": GROUP}
    ]


NO_CONTEXT = cast(DataMessageContext, None)


class Typed:
    """What Typing sends, as receipts' own functions would, faster."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[str] = []
        monkeypatch.setattr(receipts, "show_typing", self.show)
        monkeypatch.setattr(receipts, "stop_typing", self.stop)
        monkeypatch.setattr(receipts, "TYPING_AFTER", 0.2)
        monkeypatch.setattr(receipts, "TYPING_EVERY", 0.05)

    async def show(self, context: DataMessageContext) -> None:
        self.sent.append("typing")

    async def stop(self, context: DataMessageContext) -> None:
        self.sent.append("stopped")


@pytest.fixture
def typed(monkeypatch: pytest.MonkeyPatch) -> Typed:
    return Typed(monkeypatch)


async def test_typing_again_while_a_command_runs(typed: Typed) -> None:
    typing = receipts.Typing(NO_CONTEXT, at_once=True)
    await asyncio.sleep(0.17)  # at 0, 0.05, 0.10 and 0.15
    await typing.stop(answered=True)
    count = typed.sent.count("typing")
    assert 2 <= count <= 5
    assert "stopped" not in typed.sent  # the answer ends it
    await asyncio.sleep(0.1)
    assert typed.sent.count("typing") == count


async def test_typing_once_a_command_takes_a_while(typed: Typed) -> None:
    quick = receipts.Typing(NO_CONTEXT, at_once=False)
    await asyncio.sleep(0.01)
    await quick.stop(answered=True)
    assert typed.sent == []
    slow = receipts.Typing(NO_CONTEXT, at_once=False)
    await asyncio.sleep(0.22)
    await slow.stop(answered=True)
    assert typed.sent == ["typing"]


async def test_typing_for_so_long_at_most(
    typed: Typed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(receipts, "TYPING_FOR", 0.12)
    typing = receipts.Typing(NO_CONTEXT, at_once=True)
    await asyncio.sleep(0.5)
    count = typed.sent.count("typing")
    await typing.stop(answered=True)
    assert 2 <= count <= 4  # at 0, 0.05 and 0.10


async def test_typing_is_stopped_without_an_answer(typed: Typed) -> None:
    typing = receipts.Typing(NO_CONTEXT, at_once=True)
    await asyncio.sleep(0.01)
    await typing.stop(answered=False)
    assert typed.sent == ["typing", "stopped"]
    typed.sent.clear()
    unseen = receipts.Typing(NO_CONTEXT, at_once=False)
    await unseen.stop(answered=False)
    assert typed.sent == []  # nothing shown, nothing to stop


async def test_a_stop_waits_for_typing_on_its_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sending, release = asyncio.Event(), asyncio.Event()
    events: list[str] = []

    async def show(context: DataMessageContext) -> None:
        sending.set()
        await release.wait()
        events.append("typing")

    monkeypatch.setattr(receipts, "show_typing", show)
    typing = receipts.Typing(NO_CONTEXT, at_once=True)
    await sending.wait()
    stopping = asyncio.create_task(typing.stop(answered=True))
    await asyncio.sleep(0.01)
    assert not stopping.done()
    release.set()
    await stopping
    events.append("answer")
    assert events == ["typing", "answer"]


async def test_no_typing_for_a_timer(typed: Typed) -> None:
    token = collected.set([])
    try:
        typing = receipts.Typing(NO_CONTEXT, at_once=True)
        await asyncio.sleep(0.06)
        await typing.stop(answered=False)
    finally:
        collected.reset(token)
    assert typed.sent == []
