import asyncio
from typing import cast

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, GROUP, ME, FakeApi
from signalbot import DataMessage, DataMessageContext, GroupInfo, SignalBot

from nejomibot import receipts
from nejomibot.messages import Outbox, collected
from nejomibot.receipts import mark_read, show_typing

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
