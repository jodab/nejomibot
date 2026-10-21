import logging

import pytest
from aiohttp import web
from helpers import (
    ALICE,
    ALICE_ID,
    BOB,
    BOB_ID,
    CAROL_ID,
    DAVE_ID,
    GROUP,
    ME,
    ME_ID,
    FakeApi,
)
from signalbot import SignalBot

from nejomibot import access
from nejomibot.access import HEADER, Entry, Names, allowed_list, link, link_lists
from nejomibot.account import fetch_account
from nejomibot.config import get_settings

SEARCH = f"/v1/search/{ME}"
# Doesn't share his number, so signal-cli knows him by Signal ID alone
DAVE = "+46700000004"
NOT_ON_SIGNAL = "+46700000006"


@pytest.fixture
def search(signal_api: FakeApi) -> list[list[str]]:
    """Signal's contact discovery, through the fake signal-cli-rest-api: it
    finds Dave alone, and signal-cli knows his number from then on. What each
    look-up asked for."""
    asked: list[list[str]] = []

    async def look_up(request: web.Request) -> web.Response:
        numbers = request.query.getall("numbers")
        asked.append(numbers)
        if DAVE in numbers:
            everyone = signal_api.responses[f"/v1/contacts/{ME}?all"]
            everyone.append({"number": DAVE, "uuid": DAVE_ID, "name": "Dave"})
        found = [{"number": n, "registered": n == DAVE} for n in numbers]
        return web.json_response(found)

    signal_api.route("GET", SEARCH, look_up)
    return asked


async def ready() -> None:
    pass


# How people show


def test_how_people_show() -> None:
    names = Names()
    names.update({ALICE: "Alice", ALICE_ID: "Alice", CAROL_ID: "Carol"})
    names.update({GROUP: "Familjen"})
    names.numbers[ALICE_ID] = ALICE
    assert names.of(GROUP) == "Familjen"
    assert names.of("group.bm9uZQ==") == "group.bm9uZQ=="
    # By name and number, whichever names them
    assert names.of(ALICE) == f"Alice ({ALICE})"
    assert names.of(ALICE_ID) == f"Alice ({ALICE})"
    # By name alone, without a number known
    assert names.of(CAROL_ID) == "Carol"
    # By number, without a name known, or by the name given
    assert names.of(BOB) == BOB
    assert names.of(BOB, "Bobby") == f"Bobby ({BOB})"
    assert names.of(BOB, BOB) == BOB
    # By the start of their Signal ID, knowing neither
    assert names.of(DAVE_ID) == "da7e0000…"


async def test_names_take_the_lists_where_signal_cli_has_none(
    bot: SignalBot,
) -> None:
    allowed_list.reread().add(Entry(DAVE, "Dave"))
    allowed_list.add(Entry(ALICE, "Ally"))
    names = await access.names(bot)
    # signal-cli's name before the list's
    assert names.of(ALICE) == f"Alice ({ALICE})"
    assert names.of(DAVE) == f"Dave ({DAVE})"
    assert names.numbers[BOB_ID] == BOB
    assert CAROL_ID not in names.numbers


# Linking the numbers on the lists


@pytest.mark.usefixtures("signal_api")
async def test_numbers_are_looked_up_once(
    search: list[list[str]], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="nejomibot.access"):
        # Not Alice's, which signal-cli knows, nor the bot's own, nor IDs
        await link([ALICE, DAVE, NOT_ON_SIGNAL, ME, GROUP, CAROL_ID])
        await link([DAVE, NOT_ON_SIGNAL])
    assert search == [[DAVE, NOT_ON_SIGNAL]]
    assert caplog.messages == ["Looked up 2 phone numbers: Signal found 1"]


async def test_a_failed_look_up_is_tried_again(
    signal_api: FakeApi, caplog: pytest.LogCaptureFixture
) -> None:
    asked = 0

    async def rate_limited(request: web.Request) -> web.Response:
        nonlocal asked
        asked += 1
        return web.json_response({"error": "Rate limit exceeded"}, status=400)

    signal_api.route("GET", SEARCH, rate_limited)
    with caplog.at_level(logging.WARNING, logger="nejomibot.access"):
        await link([DAVE])
        await link([DAVE])
    assert asked == 2
    assert (
        caplog.messages == ["Could not look up phone numbers: Rate limit exceeded"] * 2
    )


@pytest.mark.usefixtures("search")
async def test_the_lists_get_the_names_now_known(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "wait_until_ready", ready)
    path = get_settings().allowed_file
    lines = [DAVE, f"{NOT_ON_SIGNAL}  # Someone", "# Ours", GROUP, "not anyone"]
    path.write_text("\n".join([*HEADER, *lines, ""]))
    await link_lists(bot)
    assert path.read_text().splitlines()[len(HEADER) :] == [
        f"{DAVE}  # Dave",
        # What's after a # already stays, as do comments and the unreadable
        f"{NOT_ON_SIGNAL}  # Someone",
        "# Ours",
        f"{GROUP}  # Familjen",
        "not anyone",
    ]


async def test_the_bots_own_safety_number_is_left_out(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    own = {"number": ME, "uuid": ME_ID, "status": "TRUSTED_VERIFIED", "added": "1"}
    signal_api.responses[f"/v1/identities/{ME}"].append(own)
    account = await fetch_account(bot)
    assert [i.uuid for i in account.identities] == [ALICE_ID, BOB_ID, CAROL_ID]
