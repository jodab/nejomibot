import asyncio
import os
import re
import signal
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web
from helpers import ME, ME_ID, FakeApi
from signalbot import SendMessage, SignalBot

from nejomibot import access, bot, commands, rest
from nejomibot.bot import check_aliases, handlers, load_settings, wait_for_account
from nejomibot.client import client
from nejomibot.config import get_settings
from nejomibot.i18n import languages
from nejomibot.messages import Outbox, Outcome, Posted

ADMIN = "+46700000009"
EVERYONE_ALLOWED = (True, True, "the allowed list")


def who_answers(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[object, ...]]:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    return {
        type(handler).__name__: (
            contacts,
            groups,
            "the admins" if check is access.from_admin else "the allowed list",
        )
        for handler, contacts, groups, check in handlers(
            cast(SignalBot, None), get_settings()
        )
    }


def test_who_may_use_what(monkeypatch: pytest.MonkeyPatch) -> None:
    # The admins checked for every message too, as /admin changes who they are
    admins = (True, False, "the admins")
    assert who_answers(monkeypatch) == {
        # The admins, and the allowed list, checked for every message
        "Ping": EVERYONE_ALLOWED,
        "Photo": EVERYONE_ALLOWED,
        "Albums": EVERYONE_ALLOWED,
        "OnThisDay": EVERYONE_ALLOWED,
        "Today": EVERYONE_ALLOWED,
        "Weather": EVERYONE_ALLOWED,
        "Forecast": EVERYONE_ALLOWED,
        "Info": EVERYONE_ALLOWED,
        "Fortune": EVERYONE_ALLOWED,
        "Remind": EVERYONE_ALLOWED,
        "Lists": EVERYONE_ALLOWED,
        "Birthdays": EVERYONE_ALLOWED,
        "Language": EVERYONE_ALLOWED,
        "Help": EVERYONE_ALLOWED,
        # The admins' specials that they let everyone allowed use
        "SpecialsForEveryone": EVERYONE_ALLOWED,
        # The admins, in direct chats only
        "Status": admins,
        # As it shows every group's birthdays
        "TodayPreview": admins,
        "Album": admins,
        "Specials": admins,
        "Contacts": admins,
        "Trust": admins,
        "Allowed": admins,
        "Allow": admins,
        "Disallow": admins,
        "Admins": admins,
        "Admin": admins,
        "Profile": admins,
        "Name": admins,
        "About": admins,
        "Avatar": admins,
        "Username": admins,
        "Chats": admins,
        "Timers": admins,
        "Msg": admins,
        "Run": admins,
        "Incoming": admins,
        "Birthday": admins,
        "Delivery": admins,
        # The admins, in any chat
        "Delete": (True, True, "the admins"),
    }


def test_every_handler_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    assert set(who_answers(monkeypatch)) == {h.__name__ for h in commands.handlers()}


def test_broken_config_file_stops_the_bot_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    path.write_text('account = "+46700000000"\nopenweather_api_key =\n')
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(path))
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match=r"(?s)Invalid configuration .*line 2"):
        load_settings()


def test_an_outdated_config_says_what_to_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f'phone_number = "{ME}"\nlanguage = "xx"\n')
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(path))
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as stopped:
        load_settings()
    assert str(stopped.value).splitlines()[:4] == [
        f"Invalid configuration (config file: {path}):",
        "  account: missing",
        f"  language: Value error, unknown language 'xx', not one of {languages()}",
        "  phone_number: no such setting: renamed or removed?",
    ]
    assert "/app/config.example.toml" in str(stopped.value)


def test_without_a_config_file_it_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match=r"no-config\.toml, not there\):\n  account"):
        load_settings()


def test_a_config_file_that_cant_be_read_stops_the_bot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A folder in its place, as Docker makes one to mount a file that's missing
    path = tmp_path / "config.toml"
    path.mkdir()
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(path))
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as stopped:
        load_settings()
    assert str(stopped.value) == f"Can't read the config file {path}: Is a directory."


@pytest.mark.skipif(os.geteuid() == 0, reason="root may read anything")
def test_a_config_file_out_of_reach_says_who_must_reach_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In a folder the bot's user can't open, as when the data folder is left
    # to someone else: pydantic-settings took the file to be missing, and so
    # did the message
    folder = tmp_path / "private"
    folder.mkdir()
    path = folder / "config.toml"
    path.write_text(f'account = "{ME}"\n')
    folder.chmod(0)
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(path))
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as stopped:
            load_settings()
    finally:
        folder.chmod(0o700)
    assert str(stopped.value) == (
        f"Can't read the config file {path}: Permission denied. The bot runs as "
        f"uid {os.getuid()}, which must be able to read it, and open the "
        "folders it's in."
    )


def test_no_data_dir_stops_the_bot() -> None:
    get_settings().data_dir.rmdir()
    with pytest.raises(SystemExit, match="No data_dir"):
        load_settings()


def test_a_data_dir_that_isnt_a_folder_stops_the_bot() -> None:
    data_dir = get_settings().data_dir
    data_dir.rmdir()
    data_dir.touch()
    with pytest.raises(
        SystemExit,
        match=f"^Can't write in data_dir {re.escape(str(data_dir))}: Not a directory",
    ):
        load_settings()


@pytest.mark.skipif(os.geteuid() == 0, reason="root may write anywhere")
def test_a_data_dir_the_bot_cant_write_in_stops_it() -> None:
    # The likeliest mistake: the folder left to whoever made it. The bot would
    # run, and lose what it's told.
    data_dir = get_settings().data_dir
    data_dir.chmod(0o555)
    try:
        with pytest.raises(SystemExit) as stopped:
            load_settings()
    finally:
        data_dir.chmod(0o700)
    assert str(stopped.value) == (
        f"Can't write in data_dir {data_dir}: Permission denied. The bot runs as "
        f"uid {os.getuid()}, which must be able to write in it."
    )


def test_the_data_dir_check_leaves_nothing_behind() -> None:
    data_dir = get_settings().data_dir
    before = set(data_dir.iterdir())
    load_settings()
    assert set(data_dir.iterdir()) == before


@pytest.mark.parametrize(
    ("aliases", "error"),
    [
        ('{"/fotos": ["/pic"]}', "/fotos isn't a command"),
        ('{"/photo": ["/weather"]}', "/weather is a command already"),
        ('{"/photo": ["/msg"]}', "/msg is a command already"),
    ],
)
def test_bad_aliases_stop_the_bot(
    monkeypatch: pytest.MonkeyPatch, aliases: str, error: str
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", aliases)
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match=error):
        load_settings()


@pytest.mark.usefixtures("swedish")
def test_the_swedish_names_are_good_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEJOMIBOT_ALIASES", '{"/photo": ["/pic", "pic"], "/run": ["/r"]}'
    )
    get_settings.cache_clear()
    check_aliases()


async def test_waits_for_the_account(
    signal_api: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(bot, "WAIT_RETRY", 0.01)
    signal_api.responses["/v1/accounts"] = []
    waiting = asyncio.create_task(wait_for_account())
    await signal_api.wait_for("GET", "/v1/accounts", 3)
    assert not waiting.done()
    # Said once, not at every look
    assert caplog.text.count("has no account +46700000000 yet") == 1
    assert "signal-account.sh setup" in caplog.text

    signal_api.responses["/v1/accounts"] = [ME]
    await asyncio.wait_for(waiting, 1)


NUMBERLESS = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize(
    ("listed", "accounts"),
    [
        # By number alone, as signal-cli-rest-api listed them before 787d204e
        ([ME], {ME}),
        # Since then with their Signal IDs, one without a number by that alone
        (
            [
                {"number": "", "aci": NUMBERLESS},
                {"number": ME, "aci": ME_ID},
                {"number": "", "aci": None},
            ],
            {NUMBERLESS, ME, ME_ID},
        ),
    ],
)
async def test_finds_the_account_either_way_it_is_listed(
    signal_api: FakeApi, listed: list[Any], accounts: set[str]
) -> None:
    signal_api.responses["/v1/accounts"] = listed
    assert await rest.accounts() == accounts
    await asyncio.wait_for(wait_for_account(), 1)


async def test_an_account_without_a_number(
    signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ACCOUNT", NUMBERLESS)
    get_settings.cache_clear()
    signal_api.responses["/v1/accounts"] = [{"number": "", "aci": NUMBERLESS}]
    await asyncio.wait_for(wait_for_account(), 1)
    # Its part of the API, as signal-cli-rest-api takes it since 787d204e
    assert rest.account_path("/v1/devices") == f"/v1/devices/{NUMBERLESS}"


async def test_the_wait_leaves_no_http_session_behind(signal_api: FakeApi) -> None:
    # It runs on a loop of its own, and signalbot on another after it
    await wait_for_account()
    assert client._session is None  # pyright: ignore[reportPrivateUsage]


async def test_waits_for_signal_cli_rest_api(
    signal_api: FakeApi,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(bot, "WAIT_RETRY", 0.01)

    async def starting(request: web.Request) -> web.Response:
        return web.Response(status=503, text="Starting")

    signal_api.route("GET", "/v1/accounts", starting)
    waiting = asyncio.create_task(wait_for_account())
    await signal_api.wait_for("GET", "/v1/accounts", 2)
    assert "answers with an error: Starting. Waiting." in caplog.text
    del signal_api.routes["GET", "/v1/accounts"]
    await asyncio.wait_for(waiting, 1)


async def test_waits_while_signal_cli_rest_api_is_down(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(bot, "WAIT_RETRY", 0.01)
    waiting = asyncio.create_task(wait_for_account())
    await asyncio.sleep(0.05)
    assert not waiting.done()
    waiting.cancel()
    assert caplog.text.count("Can't reach signal-cli-rest-api at 127.0.0.1:1") == 1


def test_sigterm_stops_the_bot_before_signalbot_runs() -> None:
    # As a container's first process, the bot wouldn't stop otherwise
    with pytest.raises(SystemExit) as stopped:
        bot.stop(signal.SIGTERM, None)
    assert stopped.value.code == 0


def test_shutdown_keeps_what_waits_and_closes_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # As after signalbot has stopped its loop, on SIGTERM
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def not_sent(recipient: str, message: SendMessage) -> Posted:
        return Posted(Outcome.NOT_SENT)

    outbox = Outbox(not_sent)
    monkeypatch.setattr(bot, "outbox", outbox)
    work = loop.create_task(asyncio.sleep(3600))
    loop.run_until_complete(outbox.send(ME, SendMessage(text="hej")))
    try:
        bot.shutdown()
    finally:
        asyncio.set_event_loop(None)
    assert work.cancelled()
    assert loop.is_closed()
    assert len(list(get_settings().outbox_dir.glob("*.json"))) == 1
