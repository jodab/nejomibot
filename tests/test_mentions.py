from collections.abc import AsyncIterator

import pytest
from helpers import ALICE, ALICE_ID, BOB, BOB_ID, CAROL_ID, GROUP, FakeApi, message_from
from signalbot import (
    DataMessageContext,
    Mention,
    MessageMention,
    SendMessage,
    SignalBot,
    TextMode,
    TextStyle,
)

from nejomibot import messages
from nejomibot.commands import resolved_message
from nejomibot.mentions import Mention as MentionHandler
from nejomibot.messages import Outbox, PerChat, collected, for_chat, send
from nejomibot.styles import PLACEHOLDER, mention, mentioned, written


def placed(start: int, uuid: str | None = BOB_ID, number: str | None = BOB) -> Mention:
    """A mention as signal-cli has it, where its placeholder is, in UTF-16
    code units."""
    return Mention(start=start, length=1, uuid=uuid, number=number)


# What comes in


def test_written() -> None:
    text = "/remind 18:00 ￼ and ￼!"
    assert written(text, [placed(20, CAROL_ID), placed(14)], []) == (
        f"/remind 18:00 <@{BOB_ID}> and <@{CAROL_ID}>!",
        [],
    )
    # By phone number, without a Signal ID
    assert written("￼", [placed(0, None)], [])[0] == f"<@{BOB}>"


def test_written_counts_utf16_and_moves_styles() -> None:
    # 😀 takes two code units: the placeholder is at 3, "hi" at 5
    styles = [
        TextStyle(start=3, length=1, style="BOLD"),
        TextStyle(start=5, length=2, style="ITALIC"),
    ]
    text, moved = written("😀 ￼ hi", [placed(3)], styles)
    assert text == f"😀 {mention(BOB_ID)} hi"
    longer = len(mention(BOB_ID)) - 1
    assert moved == [
        TextStyle(start=3, length=1 + longer, style="BOLD"),
        TextStyle(start=5 + longer, length=2, style="ITALIC"),
    ]


def test_odd_mentions_are_left_as_they_are() -> None:
    text = "😀 ￼"
    # Inside 😀, past the end, overlapping another, or naming nobody
    for odd in [placed(1), placed(4), placed(3, None, None)]:
        assert written(text, [odd], [])[0] == text
    both = [placed(3), Mention(start=3, length=1, uuid=CAROL_ID)]
    assert written(text, both, [])[0] == f"😀 <@{BOB_ID}>"


def test_resolved_with_its_alias() -> None:
    message = message_from(ALICE, "/lista lägg till ￼", in_group=True)
    message = message.model_copy(update={"mentions": [placed(17)]})
    resolved = resolved_message(message)
    assert resolved.text == f"/list add <@{BOB_ID}>"
    assert resolved.mentions is None


# What goes out


def test_mentioned() -> None:
    # 📣 takes two code units
    message = mentioned(SendMessage(text=f"📣 hi\n<@{ALICE_ID}> <@{BOB}>"))
    assert message.text == "📣 hi\n￼ ￼"
    assert message.mentions == [
        MessageMention(author=ALICE_ID, start=6, length=1),
        MessageMention(author=BOB, start=8, length=1),
    ]


def test_mentioned_where_a_styled_text_shows_it() -> None:
    message = mentioned(
        SendMessage(text=f"**Bold** \\* <@{BOB_ID}>", text_mode=TextMode.STYLED)
    )
    # As signal-cli-rest-api sends it: Bold * and the placeholder
    assert message.mentions == [MessageMention(author=BOB_ID, start=7, length=1)]


def test_a_placeholder_of_its_own_goes() -> None:
    message = mentioned(SendMessage(text=f"a{PLACEHOLDER} <@{BOB_ID}>"))
    assert message.text == "a ￼"
    assert message.mentions == [MessageMention(author=BOB_ID, start=2, length=1)]


def test_without_mentions_as_it_is() -> None:
    message = SendMessage(text=f"a{PLACEHOLDER} <@Bob> <@{BOB_ID[:-1]}>")
    assert mentioned(message) is message


@pytest.fixture
async def started(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Outbox]:
    """The outbox send() sends through, started."""
    outbox = Outbox()
    outbox.start(bot)
    monkeypatch.setattr(messages, "outbox", outbox)
    yield outbox
    if task := outbox._retrying:  # pyright: ignore[reportPrivateUsage]
        task.cancel()


async def test_sent_with_its_mentions(
    bot: SignalBot, signal_api: FakeApi, started: Outbox
) -> None:
    await send(bot, GROUP, SendMessage(text=f"⏰ <@{BOB_ID}> Cake"))
    [body] = signal_api.bodies("POST", "/v2/send")
    assert body["message"] == "⏰ ￼ Cake"
    assert body["mentions"] == [{"author": BOB_ID, "start": 2, "length": 1}]
    # As /delete list and /delivery show it
    sent = started.sent.pop({GROUP})
    assert sent is not None
    assert sent.start == "⏰ @ Cake"


# /mention all


async def ask(
    bot: SignalBot,
    answers: list[SendMessage],
    text: str,
    sender: str = ALICE,
    *,
    in_group: bool = True,
    edit: bool = False,
) -> list[SendMessage]:
    answers.clear()
    message = message_from(sender, text, in_group=in_group, edit=edit)
    await MentionHandler().handle_data_message(DataMessageContext(bot, message))
    return list(answers)


async def test_everyone_but_the_bot_and_the_sender(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    # The group has the bot, Alice and Carol
    [post] = await ask(bot, answers, "/mention all Dinner's\nready!")
    assert for_chat(post, GROUP).text == f"📣 Dinner's\nready!\n<@{CAROL_ID}>"
    [post] = await ask(bot, answers, "/mention ALL", BOB)
    assert for_chat(post, GROUP).text == f"📣\n<@{ALICE}> <@{CAROL_ID}>"


async def test_in_another_language(bot: SignalBot, answers: list[SendMessage]) -> None:
    [post] = await ask(bot, answers, "/nämn alla Middag!")
    assert for_chat(post, GROUP).text == f"📣 Middag!\n<@{CAROL_ID}>"


@pytest.mark.parametrize(
    ("text", "in_group"),
    [("/mention all", False), ("/mention", True), ("/mention everyone", True)],
)
async def test_how_to_use_it(
    bot: SignalBot, answers: list[SendMessage], text: str, in_group: bool
) -> None:
    [post] = await ask(bot, answers, text, in_group=in_group)
    assert (post.text or "").startswith("/mention all: mention everyone in the group")


async def test_from_a_timer(bot: SignalBot, answers: list[SendMessage]) -> None:
    # As the first admin, in a direct chat: each group gets its own people,
    # a direct chat the text alone
    token = collected.set([])
    try:
        [post] = await ask(bot, answers, "/mention all Hi", in_group=False)
        [quiet] = await ask(bot, answers, "/mention all", in_group=False)
    finally:
        collected.reset(token)
    assert isinstance(post, PerChat)
    assert for_chat(post, GROUP).text == f"📣 Hi\n<@{CAROL_ID}>"
    assert for_chat(post, BOB).text == "📣 Hi"
    assert for_chat(quiet, BOB).text == ""  # so nothing is sent


async def test_an_edit_isnt_run(bot: SignalBot, answers: list[SendMessage]) -> None:
    [post] = await ask(bot, answers, "/mention all Hi", edit=True)
    assert (post.text or "").startswith("✏️ An edit of /mention isn't run")
