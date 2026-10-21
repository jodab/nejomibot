from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from helpers import ALICE, ALICE_ID, FakeApi, text_styles
from signalbot import (
    Attachment,
    DataMessage,
    DataMessageContext,
    EditMessage,
    GroupInfo,
    RemoteDelete,
    RemoteDeleteContext,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import commands, incoming
from nejomibot.config import get_settings
from nejomibot.i18n import when_text
from nejomibot.incoming import (
    KEPT,
    Inbox,
    Incoming,
    Received,
    forward_text,
    forwards,
    list_incoming,
)
from nejomibot.messages import collected
from nejomibot.timers import Timekeeper

ADMIN = "+46700000009"
EVE = "+46700000005"  # a stranger, by the name her profile has
EVE_ID = "e7e00000-0000-4000-8000-000000000005"
# As signal-cli-rest-api tells of a photo, which it doesn't keep for the bot
PHOTO = Attachment.model_validate(
    {"contentType": "image/jpeg", "id": "x", "isVoiceNote": False}
)


class Clock:
    def __init__(self) -> None:
        # The start of this minute, so messages a second or two apart show
        # the same time
        self.now = datetime.now(UTC).replace(second=0, microsecond=0)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    """A fresh inbox, on a clock of the test's own; nobody shown the list."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    clock = Clock()
    monkeypatch.setattr(incoming, "inbox", Inbox(clock))
    monkeypatch.setattr(incoming, "shown", {})
    yield clock


def ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def message(
    text: str | None,
    *,
    sender: str = ALICE,
    sender_id: str | None = ALICE_ID,
    at: datetime | None = None,
    edits: int | None = None,
    **fields: Any,
) -> DataMessage:
    """A message to the bot in a direct chat, sent now, or at; an edit of the
    message sent at edits."""
    fields = {
        "server_delivered_timestamp": 0,
        "server_received_timestamp": 0,
        "timestamp": ms(at or datetime.now(UTC)),
        "source_number": sender,
        "source_uuid": sender_id,
        "text": text,
        **fields,
    }
    if edits is not None:
        return EditMessage(**fields, target_sent_timestamp=edits)
    return DataMessage(**fields)


def texts(inbox: Inbox) -> list[str]:
    return [received.text for received in inbox.latest()]


def test_keeps_what_anyone_but_the_admins_writes(clock: Clock) -> None:
    inbox = incoming.inbox
    group = GroupInfo.model_validate({"groupId": "internal-Familjen", "revision": 1})
    for n, each in enumerate(
        [
            message("Hej!"),
            message("/photo", sender=EVE, sender_id=None),  # commands too
            message("In the group", group_info=group),
            message("/status", sender=ADMIN),
            message(None),  # as Signal's notes of a new disappearing time
            message(None, attachments=[PHOTO]),
        ]
    ):
        # Each at a time of its own, which with its sender Signal knows it by
        inbox.keep(each.model_copy(update={"timestamp": each.timestamp + n}))
    kept = inbox.latest()
    assert [(received.text, received.attachments) for received in kept] == [
        ("", 1),
        ("/photo", 0),
        ("Hej!", 0),
    ]
    assert (kept[1].sender, kept[1].name) == (EVE, EVE)
    assert (kept[2].sender, kept[2].name) == (ALICE_ID, ALICE)


def test_keeps_only_the_latest(clock: Clock) -> None:
    for n in range(KEPT + 5):
        incoming.inbox.keep(message(f"m{n}", at=clock.now + timedelta(seconds=n)))
    kept = texts(incoming.inbox)
    assert len(kept) == KEPT
    assert (kept[0], kept[-1]) == (f"m{KEPT + 4}", "m5")


def test_an_edit_replaces_what_it_edits(clock: Clock) -> None:
    inbox = incoming.inbox
    first, second = clock.now, clock.now + timedelta(seconds=1)
    inbox.keep(message("Helo", at=first))
    inbox.keep(message("Second", at=second))
    inbox.keep(message("Hello", at=second + timedelta(seconds=1), edits=ms(first)))
    assert texts(inbox) == ["Second", "Hello"]
    # Edited again, it's known by the first one's time still
    inbox.keep(message("Hello!", at=second + timedelta(seconds=2), edits=ms(first)))
    assert texts(inbox) == ["Second", "Hello!"]
    assert inbox.latest()[1].timestamp == ms(first)


def test_an_edit_of_what_isnt_kept(clock: Clock) -> None:
    earlier = clock.now - timedelta(days=2)
    incoming.inbox.keep(message("Edited", edits=ms(earlier)))
    # Known by the time of the message it edits
    [received] = incoming.inbox.latest()
    assert (received.text, received.timestamp) == ("Edited", ms(earlier))


async def test_what_its_sender_deletes_goes(clock: Clock) -> None:
    inbox = incoming.inbox
    sent = clock.now
    inbox.keep(message("Oops", at=sent))
    inbox.keep(message("Oops", sender=EVE, sender_id=EVE_ID, at=sent))
    deleted = RemoteDelete(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        source_number=ALICE,
        source_uuid=ALICE_ID,
        timestamp=ms(sent),
    )
    await inbox.handle_remote_delete(RemoteDeleteContext(None, deleted))  # pyright: ignore[reportArgumentType]
    assert [received.sender for received in inbox.latest()] == [EVE_ID]


def test_what_disappears_goes(clock: Clock) -> None:
    inbox = incoming.inbox
    inbox.keep(message("Soon gone", at=clock.now, expires_in_seconds=60))
    inbox.keep(message("Stays", at=clock.now + timedelta(seconds=1)))
    clock.now += timedelta(seconds=59)
    assert texts(inbox) == ["Stays", "Soon gone"]
    clock.now += timedelta(seconds=2)
    assert texts(inbox) == ["Stays"]


def test_keeps_the_formatting(clock: Clock) -> None:
    text = "Look *here*: so nice"
    styles = text_styles(text, ("so nice", "BOLD"))
    incoming.inbox.keep(message(text, text_styles=styles))
    # Marks for its styles, the rest as it shows
    assert texts(incoming.inbox) == ["Look \\*here\\*: **so nice**"]


def keep_three(clock: Clock) -> None:
    """From Alice, whom the bot knows by name, Eve, a stranger by her
    profile's, and someone known only by their Signal ID."""
    stranger = "5e000000-0000-4000-8000-000000000006"
    for each in [
        message("Hej! Vem är det på bilden i morse?", at=clock.now),
        message(
            "Hi, may I use the bot?",
            sender=EVE,
            sender_id=EVE_ID,
            source_name="Eve",
            attachments=[PHOTO, PHOTO],
            at=clock.now + timedelta(seconds=1),
        ),
        message(
            "Hi", sender="", sender_id=stranger, at=clock.now + timedelta(seconds=2)
        ),
    ]:
        incoming.inbox.keep(each)


async def test_list_incoming(bot: SignalBot, clock: Clock) -> None:
    keep_three(clock)
    lines = (await list_incoming(bot, ADMIN)).splitlines()
    assert lines[0] == "📥 **Incoming messages, newest first:**"
    when = when_text(clock.now, datetime.now(UTC))
    assert lines[1:4] == [
        f"1 · {when} · 5e000000-0000-4000-8000-000000000006 · Hi",
        f"2 · {when} · Eve ({EVE}) · 📎 Hi, may I use the b…",
        f"3 · {when} · Alice ({ALICE}) · Hej! Vem är det på…",
    ]
    assert lines[4:] == [
        "",
        "/incoming <n> forwards one to you, in full; /incoming 4,9 several.",
    ]


async def test_list_nothing(bot: SignalBot, clock: Clock) -> None:
    text = await list_incoming(bot, ADMIN)
    assert text.startswith("No messages kept since the bot started, at ")


async def test_forwards(bot: SignalBot, clock: Clock) -> None:
    keep_three(clock)
    assert forwards(ADMIN, [1]) == (
        "Which ones? Send /incoming first, for their numbers."
    )
    await list_incoming(bot, ADMIN)
    incoming.inbox.keep(message("Newer", at=clock.now + timedelta(minutes=1)))
    when = when_text(clock.now, datetime.now(UTC))
    # By the numbers of the list shown, whatever came in since
    assert forwards(ADMIN, [3, 2]) == [
        f"↪️ **Alice ({ALICE})** · {when}\nHej! Vem är det på bilden i morse?",
        f"↪️ **Eve ({EVE})** · {when}\nHi, may I use the bot?\n"
        "📎 and 2 attachments, which the bot can't forward",
    ]
    assert forwards(ADMIN, [4]) == "There's no message 4: /incoming numbers them."
    assert forwards(EVE, [1]) == "Which ones? Send /incoming first, for their numbers."


async def test_forwards_what_it_is_now(bot: SignalBot, clock: Clock) -> None:
    sent = clock.now
    incoming.inbox.keep(message("Helo", at=sent))
    incoming.inbox.keep(message("Bye", at=sent + timedelta(seconds=1)))
    await list_incoming(bot, ADMIN)
    incoming.inbox.keep(message("Hello", edits=ms(sent)))
    incoming.inbox.forget(ALICE_ID, ms(sent + timedelta(seconds=1)))
    [gone, edited] = forwards(ADMIN, [1, 2])
    assert gone == "Message 1 is gone: its sender deleted it, or it disappeared."
    assert edited.endswith("\nHello")


def test_forward_text_of_a_name_marks_cant_bold(clock: Clock) -> None:
    received = Received(EVE_ID, ms(clock.now), "Eve*", "", 1)
    when = when_text(clock.now, clock.now)
    assert forward_text(received, "Eve*", clock.now) == (
        f"↪️ Eve\\* · {when}\n📎 and an attachment, which the bot can't forward"
    )


class Replies:
    """What the bot answers an admin, in a direct chat."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[SendMessage] = []

        async def nothing(context: DataMessageContext) -> None:
            pass

        monkeypatch.setattr(commands, "reply", self.reply)
        monkeypatch.setattr(commands, "mark_read", nothing)

    async def reply(self, context: DataMessageContext, message: SendMessage) -> None:
        self.sent.append(message)

    async def to(self, bot: SignalBot, text: str) -> list[str]:
        self.sent.clear()
        context = DataMessageContext(bot, message(text, sender=ADMIN, sender_id=None))
        await Incoming().handle_data_message(context)
        return [sent.text or "" for sent in self.sent]


async def test_the_command(
    bot: SignalBot, clock: Clock, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep_three(clock)
    replies = Replies(monkeypatch)
    [listed] = await replies.to(bot, "/incoming")
    assert replies.sent[0].text_mode == TextMode.STYLED
    assert listed.startswith("📥 **Incoming messages, newest first:**\n1 · ")
    forwarded = await replies.to(bot, "/incoming 3,2")
    assert [text.split("\n")[0].split(" · ")[0] for text in forwarded] == [
        f"↪️ **Alice ({ALICE})**",
        f"↪️ **Eve ({EVE})**",
    ]
    assert await replies.to(bot, "/incoming them all") == [
        "/incoming: the latest messages people sent the bot, numbered\n"
        "/incoming <n>: forward one to you, in full; /incoming 4,9 several"
    ]


async def test_a_list_posted_elsewhere_keeps_the_admins_numbers(
    bot: SignalBot, clock: Clock
) -> None:
    keep_three(clock)
    await list_incoming(bot, ADMIN)
    numbers = incoming.shown[ADMIN]
    incoming.inbox.keep(message("Newer", at=clock.now + timedelta(minutes=1)))
    # As a timer, /run or a special lists them, for others to see
    token = collected.set([])
    try:
        await list_incoming(bot, ADMIN)
    finally:
        collected.reset(token)
    assert incoming.shown[ADMIN] is numbers


async def test_run_takes_the_numbers_of_the_admin_who_sent_it(
    bot: SignalBot, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    other, other_id = "+46700000008", "0a0a0a0a-0000-4000-8000-000000000008"
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}", "{other}"]')
    get_settings.cache_clear()
    keep_three(clock)
    # The second admin was shown the list, the first wasn't
    await list_incoming(bot, other_id)
    keeper = Timekeeper()
    keeper.start(bot, [Incoming()])
    sent = message("/run 1 /incoming 3", sender=other, sender_id=other_id)
    [forwarded] = await keeper.answers_to("/incoming 3", sent)
    assert (forwarded.text or "").startswith(f"↪️ **Alice ({ALICE})** · ")
    # A timer runs it as the first admin, who has no numbers
    [answer] = await keeper.answers_to("/incoming 3")
    assert answer.text == "Which ones? Send /incoming first, for their numbers."
