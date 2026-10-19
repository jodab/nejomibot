import pytest
from helpers import ALICE, BOB, GROUP, NOW_MS, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import lists
from nejomibot.config import get_settings
from nejomibot.lists import Item, Lists, parse_line


async def ask(
    bot: SignalBot,
    answers: list[SendMessage],
    text: str,
    sender: str = ALICE,
    *,
    in_group: bool = False,
    edit: bool = False,
    timestamp: int = NOW_MS,
) -> str:
    answers.clear()
    message = message_from(
        sender, text, in_group=in_group, edit=edit, timestamp=timestamp
    )
    await Lists().handle_data_message(DataMessageContext(bot, message))
    return "\n".join(answer.text or "" for answer in answers)


def the_file() -> list[str]:
    path = get_settings().data_file("lists.txt")
    return [line for line in path.read_text().splitlines() if not line.startswith("#")]


async def test_add_remove_and_clear(bot: SignalBot, answers: list[SendMessage]) -> None:
    assert (await ask(bot, answers, "/list")).startswith("📝 The list is empty.")
    # Separated by commas, semicolons or lines, their spaces made single
    assert await ask(bot, answers, "/list add milk, eggs;\n2  kg flour,") == (
        "**📝 The list: 3 things**\n1 milk\n2 eggs\n3 2 kg flour"
    )
    assert the_file() == [f"{ALICE} | milk", f"{ALICE} | eggs", f"{ALICE} | 2 kg flour"]
    assert await ask(bot, answers, "/list remove 3,1") == (
        "🗑️ Took off: 2 kg flour, milk\n\n**📝 The list: 1 thing**\n1 eggs"
    )
    assert await ask(bot, answers, "/list clear") == "🗑️ The list is empty now."
    assert the_file() == []


async def test_each_chat_its_own(bot: SignalBot, answers: list[SendMessage]) -> None:
    await ask(bot, answers, "/list add milk", ALICE, in_group=True)
    await ask(bot, answers, "/list add *socks*", ALICE)
    # Anyone in the group shares the group's
    assert await ask(bot, answers, "/list", BOB, in_group=True) == (
        "**📝 The list: 1 thing**\n1 milk"
    )
    # As typed
    assert await ask(bot, answers, "/list", ALICE) == (
        "**📝 The list: 1 thing**\n1 \\*socks\\*"
    )
    assert the_file() == [f"{GROUP} | milk", f"{ALICE} | *socks*"]


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/list add", "/list add <things>: put things on the list"),
        ("/list add , ;", "/list add <things>"),
        (f"/list add {'x' * 201}", "A thing on the list has at most 200 characters."),
        ("/list remove", "Which? Give their numbers, as /list shows."),
        ("/list remove milk", "Which? Give their numbers"),
        ("/list remove 1", "There's no 1 on the list."),
        ("/list frobnicate", "/list add <things>"),
    ],
)
async def test_refused(
    bot: SignalBot, answers: list[SendMessage], text: str, answer: str
) -> None:
    assert (await ask(bot, answers, text)).startswith(answer)
    assert not get_settings().data_file("lists.txt").exists()


async def test_so_many_things(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lists, "MAX_ITEMS", 2)
    await ask(bot, answers, "/list add milk")
    assert await ask(bot, answers, "/list add eggs, flour") == (
        "A list has at most 2 things: take some off first."
    )


async def test_an_edit_takes_the_place_of_what_it_edits(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    added, removed = NOW_MS, NOW_MS + 5000
    await ask(bot, answers, "/list add milk, eggs, flour", timestamp=added)
    await ask(bot, answers, "/list remove 2", timestamp=removed)
    # Eggs back where they were, so 3 is what it was: flour
    assert await ask(bot, answers, "/list remove 3", edit=True, timestamp=removed) == (
        "🗑️ Took off: flour\n\n**📝 The list: 2 things**\n1 milk\n2 eggs"
    )
    assert await ask(bot, answers, "/list add milk, butter", edit=True, timestamp=added)
    assert the_file() == [f"{ALICE} | milk", f"{ALICE} | butter"]
    # Showing it runs again
    assert (await ask(bot, answers, "/list", edit=True)).startswith("**📝 The list")


def test_lines() -> None:
    assert parse_line(f"{GROUP} | milk | 2 l") == Item(GROUP, "milk | 2 l")
    for line in [f"{GROUP} |", "Bob | milk", "milk"]:
        with pytest.raises(ValueError):
            parse_line(line)
