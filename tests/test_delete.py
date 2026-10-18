from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web
from helpers import ALICE, BOB, GROUP, ME, FakeApi
from signalbot import DataMessage, DataMessageContext, EditMessage, GroupInfo, SignalBot

from nejomibot import delete
from nejomibot.config import get_settings
from nejomibot.delete import Delete, chats_of, delete_latest, nothing_text
from nejomibot.messages import Sent, SentLog

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
# As a group message names its group: by the ID signalbot calls internal
GROUP_INTERNAL_ID = "internal-Familjen"
REMOTE_DELETE = f"/v1/remote-delete/{ME}"


def ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


FAILS = ms(NOW) - 13  # the fake API won't delete this one


def log_of(*sent: Sent) -> SentLog:
    log = SentLog(lambda: NOW)
    for each in sent:
        log.add(each)
    return log


@pytest.fixture
def deletes(signal_api: FakeApi) -> FakeApi:
    """The fake signal-cli-rest-api, failing to delete FAILS."""

    async def handle_delete(request: web.Request) -> web.Response:
        if (await request.json())["timestamp"] == FAILS:
            return web.json_response({"error": "Failed to send message"}, status=400)
        return web.json_response({"timestamp": "1"})

    signal_api.route("DELETE", REMOTE_DELETE, handle_delete)
    return signal_api


def test_sent_log_pops_the_latest_in_the_chat() -> None:
    now = ms(NOW)
    log = log_of(Sent(now - 2, GROUP), Sent(now, ALICE), Sent(now - 1, GROUP))
    assert log.pop({GROUP}) == Sent(now - 1, GROUP)
    assert log.pop({GROUP}) == Sent(now - 2, GROUP)
    assert log.pop({GROUP}) is None
    assert log.pop({ALICE, "a-uuid"}) == Sent(now, ALICE)


def test_sent_log_forgets_what_signal_cant_delete() -> None:
    clock = [NOW]
    log = SentLog(lambda: clock[0])
    log.add(Sent(ms(NOW - timedelta(hours=2)), GROUP))
    log.add(Sent(ms(NOW), GROUP))
    clock[0] += timedelta(hours=23)
    assert log.pop({GROUP}) == Sent(ms(NOW), GROUP)
    assert log.pop({GROUP}) is None


async def test_delete_latest_then_the_one_before(
    bot: SignalBot, deletes: FakeApi
) -> None:
    log = log_of(Sent(ms(NOW), GROUP), Sent(ms(NOW) + 1, GROUP))
    assert await delete_latest(bot, log, {GROUP}) is None
    assert await delete_latest(bot, log, {GROUP}) is None
    assert deletes.bodies("DELETE", REMOTE_DELETE) == [
        {"recipient": GROUP, "timestamp": ms(NOW) + 1},
        {"recipient": GROUP, "timestamp": ms(NOW)},
    ]


async def test_delete_latest_keeps_what_it_couldnt_delete(
    bot: SignalBot, deletes: FakeApi
) -> None:
    log = log_of(Sent(FAILS, GROUP))
    # signalbot doesn't pass on signal-cli-rest-api's error, only its status
    assert await delete_latest(bot, log, {GROUP}) == (
        "Something went wrong: signal-cli-rest-api answered 400 Bad Request"
    )
    assert log.pop({GROUP}) == Sent(FAILS, GROUP)


def test_nothing_to_delete() -> None:
    started = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    assert nothing_text(started, started + timedelta(hours=1)) == (
        "Nothing left to delete here since the bot started, at 2026-10-12 08:00."
    )
    assert nothing_text(started, started + timedelta(days=2)) == (
        "Nothing left to delete here from the last day: Signal only deletes "
        "messages for everyone within a day."
    )


def context_of(
    bot: SignalBot, text: str, number: str, *, in_group: bool
) -> DataMessageContext:
    message = DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=ms(NOW),
        source=number,
        source_number=number,
        source_uuid=f"{number}-uuid",
        group_info=(
            GroupInfo.model_validate({"groupId": GROUP_INTERNAL_ID, "revision": 1})
            if in_group
            else None
        ),
        text=text,
    )
    return DataMessageContext(bot, message)


async def test_chats_of(bot: SignalBot) -> None:
    assert chats_of(context_of(bot, "/delete", ALICE, in_group=True)) == {GROUP}
    assert chats_of(context_of(bot, "/delete", ALICE, in_group=False)) == {
        ALICE,
        f"{ALICE}-uuid",
    }


@pytest.mark.parametrize(("sender", "deleted"), [(ALICE, True), (BOB, False)])
async def test_only_admins_delete(
    bot: SignalBot,
    deletes: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    sender: str,
    deleted: bool,
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ALICE}"]')
    get_settings.cache_clear()
    monkeypatch.setattr(delete.outbox, "sent", log_of(Sent(ms(NOW), GROUP)))
    context = context_of(bot, "/delete", sender, in_group=True)
    await Delete().handle_data_message(context)
    assert bool(deletes.bodies("DELETE", REMOTE_DELETE)) is deleted
    assert (delete.outbox.sent.pop({GROUP}) is None) is deleted


async def test_an_edit_deletes_nothing(
    bot: SignalBot, deletes: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ALICE}"]')
    get_settings.cache_clear()
    monkeypatch.setattr(delete.outbox, "sent", log_of(Sent(ms(NOW), GROUP)))
    edit = EditMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=ms(NOW),
        source_number=ALICE,
        source_uuid=f"{ALICE}-uuid",
        group_info=GroupInfo.model_validate(
            {"groupId": GROUP_INTERNAL_ID, "revision": 1}
        ),
        text="/delete",
        target_sent_timestamp=ms(NOW) - 1,
    )
    await Delete().handle_data_message(DataMessageContext(bot, edit))
    assert deletes.bodies("DELETE", REMOTE_DELETE) == []
    assert delete.outbox.sent.pop({GROUP}) == Sent(ms(NOW), GROUP)
