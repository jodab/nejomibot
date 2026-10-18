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
        "/Photo" = ["/pic", "pic"]
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
    assert settings.aliases == {"/photo": ["/pic", "pic"]}
    assert settings.allowed_file == settings.data_dir / "allowed.txt"
    assert settings.timers_file == settings.data_dir / "timers.txt"
    assert settings.sent_photos_file == settings.data_dir / "sent-photos.txt"
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
        ("NEJOMIBOT_ADMINS", '["Alice"]'),
        ("NEJOMIBOT_SIGNAL_SERVICE", "http://127.0.0.1:8080"),
        ("NEJOMIBOT_SIGNAL_SERVICE", "signal"),
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
        ("NEJOMIBOT_DEBUG_GROUP", "not-a-group"),
    ],
)
def test_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_signal_service_and_account_are_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEJOMIBOT_SIGNAL_SERVICE")
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    with pytest.raises(ValidationError, match=r"(?s)signal_service.*account"):
        Settings()  # type: ignore[call-arg]


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
