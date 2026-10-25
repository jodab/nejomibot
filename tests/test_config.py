import os
import re
import tomllib
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from nejomibot.config import Settings

GROUP = "group.dGVzdC1ncm91cA=="
SIGNAL_ID = "0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"


def write_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(text)
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(path))
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")


def test_reads_toml_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(
        tmp_path,
        monkeypatch,
        f"""
        account = "+46700000002"
        language = "sv"
        admins = ["+46700000003", "{SIGNAL_ID.upper()}"]
        photos_birth_date = 2019-06-15
        clocks = {{ "Home" = "Europe/Stockholm", "Away" = "Asia/Tokyo" }}
        exchange_rate = ["EUR", "SEK"]
        fortune_library = "startrek"
        healthcheck_url = "https://hc-ping.com/abc"

        [aliases]
        ".Photo" = ["/pic", "pix", ".pics"]
        """,
    )
    settings = Settings()  # type: ignore[call-arg]
    assert settings.account == "+46700000002"
    assert settings.language == "sv"
    # Signal IDs as signal-cli shows them, in lower case
    assert settings.admins == ["+46700000003", SIGNAL_ID]
    assert settings.photos_birth_date == date(2019, 6, 15)
    assert list(settings.clock_zones) == ["Home", "Away"]
    assert settings.exchange_rate == ("EUR", "SEK")
    assert settings.fortune_library == "startrek"
    assert settings.healthcheck_url == "https://hc-ping.com/abc"
    assert settings.healthcheck_minutes == 5
    assert settings.weather_calls_per_hour == 10
    # Each with a /: a plain word would make every message that starts with
    # it a command
    assert settings.aliases == {"/photo": ["/pic", "/pix", "/pics"]}
    assert settings.allowed_file == settings.data_dir / "allowed.txt"
    assert settings.timers_file == settings.data_dir / "timers.txt"
    assert settings.sent_photos_file == settings.data_dir / "sent-photos.txt"
    assert settings.album_rounds_file == settings.data_dir / "album-rounds.txt"
    assert settings.delete_groups is True


def test_environment_overrides_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, monkeypatch, 'account = "+46700000002"\n')
    monkeypatch.setenv("NEJOMIBOT_ACCOUNT", "+46700000001")
    monkeypatch.setenv("NEJOMIBOT_ADMINS", '["+46700000003"]')
    settings = Settings()  # type: ignore[call-arg]
    assert settings.account == "+46700000001"
    assert settings.admins == ["+46700000003"]


def test_the_environment_is_enough(tmp_path: Path) -> None:
    # The tests' environment has every setting needed, and no config file
    assert not (tmp_path / "no-config.toml").exists()
    assert Settings().account == "+46700000000"  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NEJOMIBOT_ACCOUNT", "0701234567"),
        # E.164: no country code starts with 0, and no number is that short
        ("NEJOMIBOT_ACCOUNT", "+0701234567"),
        ("NEJOMIBOT_ACCOUNT", "+467012"),
        ("NEJOMIBOT_ADMINS", '["Alice"]'),
        ("NEJOMIBOT_SIGNAL_SERVICE", "http://127.0.0.1:8080"),
        ("NEJOMIBOT_SIGNAL_SERVICE", "signal"),
        ("NEJOMIBOT_SIGNAL_SERVICE", "::1:8080"),
        ("NEJOMIBOT_WEATHER_UNITS", "kelvin"),
        ("NEJOMIBOT_TIMEZONE", "Europe/Nowhere"),
        ("NEJOMIBOT_PHOTOS_TIMEZONE", "Europe/Nowhere"),
        ("NEJOMIBOT_CLOCKS", '{"Nowhere": "Europe/Nowhere"}'),
        ("NEJOMIBOT_LANGUAGE", "xx"),
        ("NEJOMIBOT_FORTUNE_LIBRARY", "nowhere"),
        ("NEJOMIBOT_FORTUNE_LIBRARY", "list"),
        ("NEJOMIBOT_ALIASES", '{"photo": ["pic"]}'),
        ("NEJOMIBOT_ALIASES", '{"/photo": ["two words"]}'),
        ("NEJOMIBOT_EXCHANGE_RATE", '["EUR"]'),
        ("NEJOMIBOT_EXCHANGE_RATE", '["eur", "sek"]'),
        ("NEJOMIBOT_HEALTHCHECK_URL", "hc-ping.com/abc"),
        ("NEJOMIBOT_HEALTHCHECK_MINUTES", "0"),
        ("NEJOMIBOT_WEATHER_CALLS_PER_HOUR", "0"),
        ("NEJOMIBOT_DEBUG_GROUP", "not-a-group"),
        # A profile as Signal takes it: a name, About and username that fit
        ("NEJOMIBOT_BOT_NAME", " "),
        ("NEJOMIBOT_BOT_NAME", "å" * 65),
        ("NEJOMIBOT_BOT_ABOUT", "x" * 141),
        ("NEJOMIBOT_BOT_USERNAME", "1bot"),
        ("NEJOMIBOT_BOT_USERNAME", "mybot.4"),
    ],
)
def test_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "service", ["127.0.0.1:8080", "signal:8080", "[::1]:8080", "[fd00::2]:8080"]
)
def test_signal_service_by_name_or_address(
    monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    monkeypatch.setenv("NEJOMIBOT_SIGNAL_SERVICE", service)
    assert Settings().signal_service == service  # type: ignore[call-arg]


def test_signal_service_and_account_are_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEJOMIBOT_SIGNAL_SERVICE")
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    with pytest.raises(ValidationError, match=r"(?s)signal_service.*account"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "given", [SIGNAL_ID, SIGNAL_ID.upper(), SIGNAL_ID.replace("-", "").upper()]
)
def test_an_account_without_a_number_is_its_signal_id(
    monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    # With or without its dashes, as signal-cli takes it; kept as it shows it
    monkeypatch.setenv("NEJOMIBOT_ACCOUNT", given)
    assert Settings().account == SIGNAL_ID  # type: ignore[call-arg]


def test_debug_keeps_its_files_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_DEBUG", "1")
    monkeypatch.setenv("NEJOMIBOT_DEBUG_GROUP", GROUP)
    monkeypatch.setenv("NEJOMIBOT_ADMINS", '["+46700000004"]')
    settings = Settings()  # type: ignore[call-arg]
    # The admins keep their commands, which only answer them
    assert settings.admins == ["+46700000004"]
    assert settings.delete_groups == [GROUP]
    for path in (
        settings.sent_photos_file,
        settings.timers_file,
        settings.allowed_file,
    ):
        assert settings.data_dir not in path.parents
        # In a folder of its own, which only the bot's user may enter
        assert path.parent.name.startswith("nejomibot-")
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_debug_needs_debug_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_DEBUG", "1")
    with pytest.raises(ValidationError, match="debug_group"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize("setting", ["typo = 1", 'phone_number = "+46700000002"'])
def test_rejects_unknown_file_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    # Settings that were renamed or are gone too: the config must be updated
    write_config(tmp_path, monkeypatch, f'account = "+46700000002"\n{setting}\n')
    with pytest.raises(ValidationError, match=setting.split()[0]):
        Settings()  # type: ignore[call-arg]


ROOT = Path(__file__).parent.parent


def test_the_example_has_every_setting_as_it_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Copied to config.toml with every setting it shows given, commented out
    # or not, it reads; only debug is told of as NEJOMIBOT_DEBUG
    example = (ROOT / "config.example.toml").read_text()
    given = re.sub(r"(?m)^# ([a-z_]+ = )", r"\1", example)
    for name in os.environ:
        if name.startswith("NEJOMIBOT_"):
            monkeypatch.delenv(name)
    path = tmp_path / "config.toml"
    path.write_text(given)
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(path))
    settings = Settings()  # type: ignore[call-arg]
    assert set(Settings.model_fields) - set(tomllib.loads(given)) == {"debug"}
    assert settings.command_limit == 20


def test_a_username_may_start_with_an_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_BOT_USERNAME", "@mybot.42")
    assert Settings().bot_username == "mybot.42"  # type: ignore[call-arg]
