import asyncio
import signal
from pathlib import Path
from typing import cast

import pytest
from aiohttp import web
from helpers import ME, FakeApi
from signalbot import SendMessage, SignalBot

from nejomibot import bot, commands
from nejomibot.bot import check_aliases, handlers, load_settings, wait_for_account
from nejomibot.client import client
from nejomibot.config import get_settings
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
            *(["the allowed list"] if check else []),
        )
        for handler, contacts, groups, check in handlers(
            cast(SignalBot, None), get_settings()
        )
    }


def test_who_may_use_what(monkeypatch: pytest.MonkeyPatch) -> None:
    admins = ([ADMIN], False)
    assert who_answers(monkeypatch) == {
        # The admins, and the allowed list, checked for every message
        "Ping": EVERYONE_ALLOWED,
        "Photo": EVERYONE_ALLOWED,
        "Weather": EVERYONE_ALLOWED,
        "Info": EVERYONE_ALLOWED,
        "Fortune": EVERYONE_ALLOWED,
        "Help": EVERYONE_ALLOWED,
        # The admins, in direct chats only
        "Status": admins,
        "Specials": admins,
        "Contacts": admins,
        "Trust": admins,
        "Allowed": admins,
        "Allow": admins,
        "Disallow": admins,
        "Profile": admins,
        "Name": admins,
        "About": admins,
        "Avatar": admins,
        "Username": admins,
        "Chats": admins,
        "Timers": admins,
        "Msg": admins,
        "Run": admins,
        # Any chat, but in groups it checks for an admin itself
        "Delete": ([ADMIN], True),
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
        "  language: Value error, unknown language 'xx', not one of ['en', 'sv']",
        "  phone_number: no such setting: renamed or removed?",
    ]
    assert "/app/config.example.toml" in str(stopped.value)


def test_without_a_config_file_it_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    get_settings.cache_clear()
    with pytest.raises(SystemExit, match=r"no-config\.toml, not there\):\n  account"):
        load_settings()


def test_no_data_dir_stops_the_bot() -> None:
    get_settings().data_dir.rmdir()
    with pytest.raises(SystemExit, match="No data_dir"):
        load_settings()


@pytest.mark.parametrize(
    ("aliases", "error"),
    [
        ('{"/fotos": ["/pic"]}', "/fotos isn't a command"),
        ('{"/photo": ["/weather"]}', "/weather is a command already"),
        ('{"/photo": ["/time"]}', "/time is a command already"),
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
