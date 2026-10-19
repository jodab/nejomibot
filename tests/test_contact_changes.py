import pytest
from helpers import (
    ALICE_ID,
    BOB,
    BOB_ID,
    CAROL_ID,
    EDIT_FROM_BEFORE,
    ME,
    FakeApi,
    message_from,
)
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import contacts
from nejomibot.account import Account
from nejomibot.contacts import Contacts, add, add_contact, split_who

CONTACTS = f"/v1/contacts/{ME}"


async def test_add(bot: SignalBot, account: Account, signal_api: FakeApi) -> None:
    text = await add(bot, account, BOB, "Bobby")
    assert text == "📇 Added Bob Berg to the contacts, as Bobby."
    assert signal_api.bodies("PUT", CONTACTS) == [
        {"recipient": BOB_ID, "name": "Bobby"}
    ]


async def test_add_renames_a_contact(bot: SignalBot, account: Account) -> None:
    assert await add(bot, account, "alice", "Ali") == (
        "✏️ Renamed Alice to Ali in the contacts."
    )


async def test_add_someone_by_their_id(
    bot: SignalBot, account: Account, signal_api: FakeApi
) -> None:
    text = await add(bot, account, CAROL_ID, "Carl")
    assert text == f"📇 Added {CAROL_ID} to the contacts, as Carl."
    assert signal_api.bodies("PUT", CONTACTS) == [
        {"recipient": CAROL_ID, "name": "Carl"}
    ]


async def test_add_someone_new_by_phone_number(
    bot: SignalBot, account: Account, signal_api: FakeApi
) -> None:
    text = await add(bot, account, "+46700000009", "Dora")
    assert text == "📇 Added +46700000009 to the contacts, as Dora."
    assert signal_api.bodies("PUT", CONTACTS) == [
        {"recipient": "+46700000009", "name": "Dora"}
    ]


def test_split_who_takes_the_longest_name(account: Account) -> None:
    assert split_who(account, ["Bob", "Berg", "Bobby", "B"]) == ("Bob Berg", "Bobby B")
    assert split_who(account, ["alice", "Ali"]) == ("alice", "Ali")
    assert split_who(account, ["Carol", "C", "D"]) == ("Carol", "C D")


async def test_add_by_a_name_with_spaces(bot: SignalBot) -> None:
    assert await add_contact(bot, ["Bob", "Berg", "Bobby"]) == (
        "📇 Added Bob Berg to the contacts, as Bobby."
    )


async def test_add_nobody(
    bot: SignalBot, account: Account, signal_api: FakeApi
) -> None:
    text = await add(bot, account, "Carol", "C")
    assert text == "Nobody called Carol in /contacts."
    assert signal_api.bodies("PUT", CONTACTS) == []


async def test_usage(bot: SignalBot, signal_api: FakeApi) -> None:
    assert (await add_contact(bot, [BOB])).startswith("Send: /contacts add")
    assert signal_api.requests == []


async def test_an_edit_of_a_message_from_before_a_start(
    bot: SignalBot,
    signal_api: FakeApi,
    answers: list[SendMessage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_account(bot: SignalBot) -> Account:
        raise AssertionError("an edit mustn't get this far")

    monkeypatch.setattr(contacts, "fetch_account", fetch_account)
    text = f"/contacts add {CAROL_ID} Carl"
    message = message_from(BOB, text, edit=True, timestamp=1)
    await Contacts().handle_data_message(DataMessageContext(bot, message))
    # The bot can't tell what the message it edits did
    assert [answer.text for answer in answers] == [EDIT_FROM_BEFORE]
    assert signal_api.requests == []


async def test_an_edit_renames_in_its_place(
    bot: SignalBot, signal_api: FakeApi, answers: list[SendMessage]
) -> None:
    first = message_from(BOB, "/contacts add alice Ali")
    await Contacts().handle_data_message(DataMessageContext(bot, first))
    edit = message_from(BOB, "/contacts add alice Ally", edit=True)
    await Contacts().handle_data_message(DataMessageContext(bot, edit))
    # The name the first gave is undone, then the edit's given
    assert signal_api.bodies("PUT", CONTACTS) == [
        {"recipient": ALICE_ID, "name": "Ali"},
        {"recipient": ALICE_ID, "name": "Alice"},
        {"recipient": ALICE_ID, "name": "Ally"},
    ]
    assert [answer.text for answer in answers] == [
        "✏️ Renamed Alice to Ali in the contacts.",
        "✏️ Renamed Alice to Ally in the contacts.",
    ]
