from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, BOB, GROUP, ME, FakeApi
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    GroupInfo,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import commands, delete
from nejomibot.config import get_settings
from nejomibot.delete import (
    LISTED,
    Delete,
    delete_latest,
    delete_listed,
    list_sent,
    nothing_sent_text,
    nothing_text,
    start_text,
)
from nejomibot.messages import Sent, SentLog, chats_of

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


@pytest.fixture(autouse=True)
def nothing_shown() -> Iterator[None]:
    """No admin has been shown the list yet, as at a start."""
    delete.shown.clear()
    yield
    delete.shown.clear()


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


def test_sent_log_lists_the_latest_in_every_chat() -> None:
    now = ms(NOW)
    log = log_of(Sent(now - 2, GROUP), Sent(now, ALICE), Sent(now - 1, GROUP))
    assert log.latest(2) == [Sent(now, ALICE), Sent(now - 1, GROUP)]
    assert log.latest(20) == [
        Sent(now, ALICE),
        Sent(now - 1, GROUP),
        Sent(now - 2, GROUP),
    ]


def test_sent_log_takes_a_message_out() -> None:
    clock = [NOW]
    log = SentLog(lambda: clock[0])
    old, new = Sent(ms(NOW - timedelta(hours=2)), GROUP), Sent(ms(NOW), ALICE)
    log.add(old)
    log.add(new)
    assert log.take(new)
    assert not log.take(new)
    clock[0] += timedelta(hours=23)  # too old for Signal to delete
    assert not log.take(old)
    assert log.latest(20) == []


def test_sent_of_a_message() -> None:
    caption = "**Photo of the day\\!**\n\n📅 2026-10-12 08:00"
    photo = SendMessage(
        text=caption, base64_attachments=["aGVq"], text_mode=TextMode.STYLED
    )
    assert Sent.of(1, GROUP, photo) == Sent(1, GROUP)
    sent = Sent.of(1, GROUP, photo)
    assert (sent.start, sent.styled, sent.photo) == (
        "**Photo of the day\\!**",
        True,
        True,
    )
    sent = Sent.of(2, ALICE, SendMessage(text="\n pong!\nmore"))
    assert (sent.start, sent.styled, sent.photo) == ("pong!", False, False)


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


# /delete list, and /delete <n>


@pytest.mark.parametrize(
    ("sent", "text"),
    [
        (Sent(1, GROUP, "pong!"), "pong!"),
        # As it shows: marks read, as signal-cli-rest-api reads them
        (Sent(1, GROUP, "**Photo** \\*1\\*", styled=True), "Photo *1*"),
        (Sent(1, GROUP, "**Photo** \\*1\\*"), "**Photo** \\*1\\*"),
        (Sent(1, GROUP, "Aldrig är dagen så lång att inte"), "Aldrig är dagen så…"),
        (Sent(1, GROUP, "Dagens bild!", styled=True, photo=True), "📷 Dagens bild!"),
        (Sent(1, GROUP, "", photo=True), "📷"),
    ],
)
def test_start_text(sent: Sent, text: str) -> None:
    assert start_text(sent) == text


def test_nothing_sent() -> None:
    started = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    assert nothing_sent_text(started, started + timedelta(hours=1)) == (
        "The bot has sent nothing since it started, at 2026-10-12 08:00."
    )
    assert nothing_sent_text(started, started + timedelta(days=2)) == (
        "The bot has sent nothing in the last day, and Signal only deletes "
        "messages for everyone within a day."
    )


def latest_of(*texts: str, chat: str = GROUP) -> SentLog:
    """A log of messages that start with the texts, one a minute, the last
    sent now."""
    log = SentLog()
    now = datetime.now(UTC)
    for i, text in enumerate(reversed(texts)):
        log.add(Sent(ms(now - timedelta(minutes=i)), chat, text))
    return log


async def test_list_sent(bot: SignalBot) -> None:
    stranger = "+46700000005"
    log = latest_of("first")
    log.add(Sent(ms(datetime.now(UTC)) + 1, ALICE, "pong!"))
    log.add(Sent(ms(datetime.now(UTC)) + 2, stranger, "Hi"))
    lines = (await list_sent(bot, log, ALICE_ID)).splitlines()
    assert lines[0] == "📤 **The bot's latest messages, newest first:**"
    # Where to, by name; one the bot doesn't know by name, by number
    assert [line.split(" · ", 1)[0] for line in lines[1:4]] == ["1", "2", "3"]
    assert lines[1].endswith(f" · 👤 {stranger} · Hi")
    assert lines[2].endswith(" · 👤 Alice · pong!")
    assert lines[3].endswith(" · 👥 Familjen · first")
    assert lines[4:] == [
        "",
        "/delete <n> deletes one for everyone; /delete 2,5,11 several.",
    ]


async def test_list_sent_shows_the_latest_fifty(bot: SignalBot) -> None:
    log = latest_of(*(f"m{n}" for n in range(LISTED + 5)))
    lines = (await list_sent(bot, log, ALICE_ID)).splitlines()
    assert lines[1].endswith(f" · m{LISTED + 4}")
    assert lines[LISTED].endswith(" · m5")
    assert lines[LISTED + 1 :] == [
        "",
        "/delete <n> deletes one for everyone; /delete 2,5,11 several.",
    ]


async def test_list_sent_escapes(bot: SignalBot) -> None:
    log = latest_of("*not bold*")
    text = await list_sent(bot, log, ALICE_ID)
    assert text.splitlines()[1].endswith(" · \\*not bold\\*")


async def test_list_nothing(bot: SignalBot) -> None:
    text = await list_sent(bot, SentLog(), ALICE_ID)
    assert text.startswith("The bot has sent nothing since it started, at ")


async def test_delete_listed(bot: SignalBot, deletes: FakeApi) -> None:
    log = latest_of("first", "second", "third")
    first, second, _third = log.latest(20)[::-1]
    await list_sent(bot, log, ALICE_ID)
    log.add(Sent(ms(datetime.now(UTC)) + 1, ALICE, "fourth"))  # numbers stay
    text = await delete_listed(bot, log, ALICE_ID, [2])
    assert text.startswith("🗑️ **Deleted**\n2 · ")
    assert text.endswith(" · 👥 Familjen · second")
    assert await delete_listed(bot, log, ALICE_ID, [3]) == (
        "🗑️ **Deleted**\n" + delete.shown[ALICE_ID][2][1]
    )
    assert deletes.bodies("DELETE", REMOTE_DELETE) == [
        {"recipient": GROUP, "timestamp": second.timestamp},
        {"recipient": GROUP, "timestamp": first.timestamp},
    ]
    assert [sent.start for sent in log.latest(20)] == ["fourth", "third"]


async def test_delete_listed_twice(bot: SignalBot, deletes: FakeApi) -> None:
    log = latest_of("first")
    await list_sent(bot, log, ALICE_ID)
    await delete_listed(bot, log, ALICE_ID, [1])
    assert await delete_listed(bot, log, ALICE_ID, [1]) == (
        "Message 1 is gone already: deleted, or too old for Signal to delete."
    )
    assert len(deletes.bodies("DELETE", REMOTE_DELETE)) == 1


async def test_delete_listed_by_a_number_not_listed(
    bot: SignalBot, deletes: FakeApi
) -> None:
    log = latest_of("first")
    assert await delete_listed(bot, log, ALICE_ID, [1]) == (
        "Which ones? Send /delete list first, for their numbers."
    )
    await list_sent(bot, log, ALICE_ID)
    # The numbers of the list each admin was shown
    assert await delete_listed(bot, log, BOB, [1]) == (
        "Which ones? Send /delete list first, for their numbers."
    )
    # Not one is deleted if any isn't listed
    for numbers in ([0], [1, 2]):
        assert await delete_listed(bot, log, ALICE_ID, numbers) == (
            f"There's no message {numbers[-1]}: /delete list numbers them."
        )
    assert deletes.bodies("DELETE", REMOTE_DELETE) == []


async def test_delete_listed_keeps_what_it_couldnt_delete(
    bot: SignalBot, deletes: FakeApi
) -> None:
    log = log_of(Sent(FAILS, GROUP, "first"))
    await list_sent(bot, log, ALICE_ID)
    # signalbot doesn't pass on signal-cli-rest-api's error, only its status
    assert await delete_listed(bot, log, ALICE_ID, [1]) == (
        "Something went wrong: signal-cli-rest-api answered 400 Bad Request"
    )
    assert log.latest(20) == [Sent(FAILS, GROUP)]


async def test_delete_several(bot: SignalBot, deletes: FakeApi) -> None:
    log = latest_of("first", "second", "third", "fourth")
    await list_sent(bot, log, ALICE_ID)
    await delete_listed(bot, log, ALICE_ID, [2])
    # In the order given; one gone already said so, after them
    text = await delete_listed(bot, log, ALICE_ID, [4, 2, 1])
    deleted, gone = text.split("\n\n")
    assert [line.split(" · ")[-1] for line in deleted.splitlines()] == [
        "🗑️ **Deleted**",
        "first",
        "fourth",
    ]
    assert gone == (
        "Message 2 is gone already: deleted, or too old for Signal to delete."
    )
    assert [sent.start for sent in log.latest(20)] == ["second"]


async def test_delete_several_stops_where_one_fails(
    bot: SignalBot, deletes: FakeApi
) -> None:
    # As when Signal can't be reached, where the rest would fail too
    log = log_of(
        Sent(ms(NOW) - 1, GROUP, "newest"),
        Sent(FAILS, GROUP, "fails"),
        Sent(ms(NOW) - 20, GROUP, "oldest"),
    )
    await list_sent(bot, log, ALICE_ID)
    text = await delete_listed(bot, log, ALICE_ID, [1, 2, 3])
    assert text.split("\n\n")[1:] == [
        "Something went wrong: signal-cli-rest-api answered 400 Bad Request\n"
        "Not tried after that: 3"
    ]
    assert text.startswith("🗑️ **Deleted**\n1 · ")
    assert [sent.start for sent in log.latest(20)] == ["fails", "oldest"]


class Replies:
    """What the bot answers in a chat: its texts and whether styled."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[SendMessage] = []
        monkeypatch.setattr(commands, "reply", self.reply)

    async def reply(self, context: DataMessageContext, message: SendMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def replies(monkeypatch: pytest.MonkeyPatch) -> Replies:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ALICE}"]')
    get_settings.cache_clear()
    monkeypatch.setattr(delete.outbox, "sent", latest_of("first", "second"))
    return Replies(monkeypatch)


async def test_list_and_delete_in_a_direct_chat(
    bot: SignalBot, deletes: FakeApi, replies: Replies
) -> None:
    await Delete().handle_data_message(
        context_of(bot, "/delete LIST", ALICE, in_group=False)
    )
    [listed] = replies.sent
    assert listed.text_mode == TextMode.STYLED
    assert (listed.text or "").startswith("📤 **The bot's latest messages")
    await Delete().handle_data_message(
        context_of(bot, "/delete #2", ALICE, in_group=False)
    )
    assert (replies.sent[1].text or "").endswith(" · 👥 Familjen · first")
    assert [sent.start for sent in delete.outbox.sent.latest(20)] == ["second"]


async def test_delete_several_in_a_direct_chat(
    bot: SignalBot, deletes: FakeApi, replies: Replies
) -> None:
    await Delete().handle_data_message(
        context_of(bot, "/delete list", ALICE, in_group=False)
    )
    await Delete().handle_data_message(
        context_of(bot, "/delete 2, 1", ALICE, in_group=False)
    )
    assert (replies.sent[1].text or "").splitlines()[0] == "🗑️ **Deleted**"
    assert delete.outbox.sent.latest(20) == []


@pytest.mark.parametrize("text", ["/delete list", "/delete 1", "/delete it"])
async def test_only_the_latest_in_a_group(
    bot: SignalBot, deletes: FakeApi, replies: Replies, text: str
) -> None:
    # The list shows what went to every chat, people's too
    await Delete().handle_data_message(context_of(bot, text, ALICE, in_group=True))
    assert replies.sent == []
    assert delete.shown == {}
    assert deletes.bodies("DELETE", REMOTE_DELETE) == []


@pytest.mark.parametrize("text", ["/delete them all", "/delete 1,x", "/delete 12345"])
async def test_usage(bot: SignalBot, replies: Replies, text: str) -> None:
    await Delete().handle_data_message(context_of(bot, text, ALICE, in_group=False))
    [usage] = replies.sent
    assert (usage.text or "").splitlines() == [
        "/delete: delete the bot's latest message here, for everyone",
        "/delete list: its latest messages, wherever it sent them",
        "/delete <n>: delete one of those for everyone; /delete 2,5,11 several",
    ]


async def test_an_edit_deletes_nothing_by_number(
    bot: SignalBot, deletes: FakeApi, replies: Replies
) -> None:
    log = delete.outbox.sent
    await list_sent(bot, log, f"{ALICE}-uuid")
    edit = EditMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=ms(NOW),
        source_number=ALICE,
        source_uuid=f"{ALICE}-uuid",
        text="/delete 1",
        target_sent_timestamp=ms(NOW) - 1,
    )
    await Delete().handle_data_message(DataMessageContext(bot, edit))
    # A deletion can't be undone, so an edit of one isn't run, and says so
    assert [message.text for message in replies.sent] == [
        "✏️ An edit of /delete isn't run, as what it did can't be undone. Send "
        "it as a new message instead."
    ]
    assert deletes.bodies("DELETE", REMOTE_DELETE) == []
