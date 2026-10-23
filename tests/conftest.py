import logging
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from helpers import ME, FakeApi
from signalbot import (
    Config,
    ConnectionMode,
    DataMessageContext,
    InMemoryConfig,
    SendMessage,
    SignalBot,
)

from nejomibot import (
    access,
    backups,
    birthdays,
    commands,
    contacts,
    healthcheck,
    i18n,
    lists,
    photos,
    reminders,
    specials,
    system,
    weather,
)

# bot imports every handler, as it does when the bot runs: commands.known()
# knows the commands of those Python has read
from nejomibot import bot as _bot  # noqa: F401  # pyright: ignore[reportUnusedImport]
from nejomibot.account import Account, fetch_account
from nejomibot.client import client
from nejomibot.config import debug_folder, get_settings

TEST_ENV = {
    "NEJOMIBOT_ACCOUNT": ME,
    "NEJOMIBOT_OPENWEATHER_API_KEY": "test-key",
    "NEJOMIBOT_WEATHER_CITY": "Stockholm",
    # Nothing listens there, so no test reaches a real bot's Signal
    "NEJOMIBOT_SIGNAL_SERVICE": "127.0.0.1:1",
}


@pytest.fixture(autouse=True)
def settings_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test fresh settings that don't depend on the real config."""
    for name in os.environ:
        if name.startswith("NEJOMIBOT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(tmp_path / "no-config.toml"))
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_DIR", str(tmp_path / "photos"))
    # Where the bot keeps its files: there for every test
    monkeypatch.setenv("NEJOMIBOT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    for name, value in TEST_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    debug_folder.cache_clear()  # each test's debug mode starts anew
    yield
    get_settings.cache_clear()
    debug_folder.cache_clear()


@pytest.fixture(autouse=True)
def fresh_lists() -> None:
    """The allowed list, the admins added, the admins' specials, the
    reminders, lists, birthdays, albums' birth dates and chats' languages as
    the bot has them at a start: it keeps them for good. Nor has
    OpenWeatherMap been asked yet, nor a photo read for when it was taken,
    nor anyone shown a numbered list."""
    access.allowed_list.reset()
    access.admin_list.reset()
    access.looked_up.clear()
    specials.own_specials.__init__()
    for kept in (
        reminders.kept,
        lists.kept,
        birthdays.kept,
        photos.birth_dates,
        i18n.chat_languages,
    ):
        kept.reset()
    birthdays.shown.clear()
    contacts.shown.clear()
    # Nor any backup made, or failed
    backups.last_failure = backups.unchanged_at = None
    # Nor what commands did, for edits of them
    commands.done.clear()
    weather.places.clear()
    weather.latest.clear()
    weather.forecasts.clear()
    weather.calls.clear()
    photos.taken.clear()


@pytest.fixture(autouse=True)
async def http_client() -> AsyncIterator[None]:
    """The bot's HTTP session, closed after each test, as each has its own
    event loop."""
    yield
    await client.close()


@pytest.fixture(autouse=True)
def socket_name(monkeypatch: pytest.MonkeyPatch) -> str:
    """A health check socket of the test's own, apart from any running bot's,
    as the bot answers on it while it waits for the account, too."""
    name = f"\0nejomibot-test-{uuid.uuid4()}"
    monkeypatch.setattr(healthcheck, "SOCKET", name)
    return name


@pytest.fixture
def swedish(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot speaks Swedish, as it always has."""
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", "sv")
    get_settings.cache_clear()


@pytest.fixture
def photos_dir() -> Path:
    path = get_settings().photos_dir
    path.mkdir()
    return path


@pytest.fixture
def fake_system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point /proc and /sys at empty folders: tmp_path/proc and tmp_path/sys."""
    monkeypatch.setattr(system, "PROC", tmp_path / "proc")
    monkeypatch.setattr(system, "SYS", tmp_path / "sys")
    (tmp_path / "proc/self").mkdir(parents=True)
    (tmp_path / "sys/fs/cgroup").mkdir(parents=True)
    return tmp_path


@pytest.fixture
async def signal_api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeApi]:
    """A fake signal-cli-rest-api, which the bot's settings point to."""
    api = FakeApi()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", api.handle)
    async with TestServer(app, host="127.0.0.1") as server:
        url = server.make_url("/")
        monkeypatch.setenv("NEJOMIBOT_SIGNAL_SERVICE", f"{url.host}:{url.port}")
        get_settings.cache_clear()
        yield api


@pytest.fixture
async def bot(signal_api: FakeApi) -> AsyncIterator[SignalBot]:
    """A real signalbot, talking to the fake signal-cli-rest-api, with the
    groups it lists."""
    signalbot_logger = logging.getLogger("signalbot")
    handlers = list(signalbot_logger.handlers)
    settings = get_settings()
    bot = SignalBot(
        Config(
            signal_service=settings.signal_service,
            phone_number=settings.account,
            connection_mode=ConnectionMode.HTTP_ONLY,
            download_attachments=False,
            storage=InMemoryConfig(),
        )
    )
    await bot.groups.refresh()
    signal_api.requests.clear()
    yield bot
    await bot.close()
    signalbot_logger.handlers = handlers  # each bot adds one


@pytest.fixture
async def account(bot: SignalBot) -> Account:
    return await fetch_account(bot)


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[SendMessage]:
    """What commands answer, kept here rather than sent; they mark nothing
    read, nor show typing."""
    found: list[SendMessage] = []

    async def reply(context: DataMessageContext, message: SendMessage) -> None:
        found.append(message)

    async def nothing(context: DataMessageContext) -> None:
        pass

    monkeypatch.setattr(commands, "reply", reply)
    monkeypatch.setattr(commands, "mark_read", nothing)
    monkeypatch.setattr(commands, "show_typing", nothing)
    return found
