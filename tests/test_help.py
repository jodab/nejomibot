import re
from pathlib import Path
from typing import cast

import pytest
from signalbot import SignalBot

from nejomibot.bot import handlers
from nejomibot.config import get_settings
from nejomibot.help import ADMIN, ANYWHERE, EVERYDAY, help_message


def commands(*, everyday: bool) -> set[str]:
    """The commands of the handlers for everyone allowed, or for the admins."""
    return {
        command.name
        for handler, _contacts, _groups, check in handlers(
            cast(SignalBot, None), get_settings()
        )
        if (check is not None) == everyday
        for command in handler.commands
    }


def test_help_has_every_command_in_its_place() -> None:
    assert {line.name for line in EVERYDAY} == commands(everyday=True)
    assert {line.name for line in ADMIN + ANYWHERE} == commands(everyday=False)


def test_the_readme_has_every_command() -> None:
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    for command in commands(everyday=True) | commands(everyday=False):
        assert f"| `{command}" in readme, command


def listed(command: str, text: str) -> bool:
    return bool(re.search(rf"`{re.escape(command)}[ `]", text))


def test_admins_see_every_command() -> None:
    text = help_message(admin=True)
    for command in commands(everyday=True) | commands(everyday=False):
        assert listed(command, text), command
    assert "in Stockholm time" in text


def test_others_see_the_everyday_commands() -> None:
    text = help_message(admin=False)
    for command in commands(everyday=True):
        assert listed(command, text), command
    for command in commands(everyday=False):
        assert not listed(command, text), command


def test_a_line_per_command() -> None:
    # Short lines, as Signal's bubbles are narrow: icon, command, what it does
    lines = help_message(admin=False).splitlines()
    assert lines[0] == "**Commands**"
    assert lines[1] == "📷 `/photo` – a random photo"
    assert lines[6] == "🔮 `/fortune [<library>|all|list]` – a fortune"


def test_aliases_are_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic", "pic"]}')
    get_settings.cache_clear()
    assert "📷 `/photo` – a random photo (/pic, pic)" in help_message(admin=False)


def test_the_bots_own_aliases_are_listed() -> None:
    text = help_message(admin=True)
    assert "🕰️ `/info` – the time, and an exchange rate (/time)" in text
    assert "🩺 `/status` – how the bot and the server are (/test)" in text
    assert "👥 `/contacts [<who>]` – who the bot knows (/safety)" in text
    # On the command's first line only
    assert "📇 `/contacts add <who> <name>` – add a contact, or rename\n" in text


def test_an_alias_is_listed_by_the_command_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The config's, before the bot's own
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/test"], "/status": ["/s"]}')
    get_settings.cache_clear()
    text = help_message(admin=True)
    assert "📷 `/photo` – a random photo (/test)" in text
    assert "🩺 `/status` – how the bot and the server are (/s)" in text


@pytest.mark.usefixtures("swedish")
def test_in_swedish() -> None:
    text = help_message(admin=True)
    # By their Swedish names, which they have
    assert "🌤️ `/väder` – vädret just nu" in text
    assert "🔐 `/verifiera <vem> <säkerhetsnummer>` – markera som verifierad" in text
    assert "⏰ `/timers` – det boten kör på schema" in text
    assert "enligt tiden i Stockholm" in text
    assert text.endswith("Alla kommandon fungerar också med sina engelska namn.")
