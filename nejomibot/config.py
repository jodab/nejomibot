"""Settings, read from a TOML file and NEJOMIBOT_* environment variables.

The file is config.toml in the working directory, or the path in
NEJOMIBOT_CONFIG (/data/config.toml in the container). It may be left out
when the environment has every setting needed. Environment variables override
the file, e.g. NEJOMIBOT_OPENWEATHER_API_KEY or NEJOMIBOT_DEBUG=1.
"""

import os
import re
import tempfile
from datetime import date
from functools import cache, cached_property
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    Field,
    PositiveFloat,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


def valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown timezone {value!r}") from e
    return value


PHONE_NUMBER = r"^\+\d{6,15}$"
GROUP_ID = r"^group\.[A-Za-z0-9+/=]+$"
# A Signal account's ID (its ACI), as signal-cli shows it
SIGNAL_ID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def valid_person(value: str) -> str:
    if not (re.match(PHONE_NUMBER, value) or re.match(SIGNAL_ID, value)):
        raise ValueError(f"{value!r} is neither a phone number (+…) nor a Signal ID")
    return value


GroupId = Annotated[str, StringConstraints(pattern=GROUP_ID)]
# Someone on Signal: by phone number, or by Signal ID for those who don't
# share their number
Person = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(valid_person),
]
TimeZone = Annotated[str, AfterValidator(valid_timezone)]
HostPort = Annotated[str, StringConstraints(pattern=r"^[^:/\s]+:\d+$")]
# A command, as its handler names it, and another name for it: one word each
Command = Annotated[str, StringConstraints(pattern=r"^/\S+$", to_lower=True)]
Alias = Annotated[str, StringConstraints(pattern=r"^\S+$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


def config_file() -> Path:
    return Path(os.environ.get("NEJOMIBOT_CONFIG", "config.toml"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEJOMIBOT_", extra="forbid")

    # Signal: where signal-cli-rest-api (json-rpc mode) answers, as host:port,
    # and the bot's account in it. The account is a phone number for now; it
    # may be a Signal ID once signal-cli-rest-api has accounts without one.
    signal_service: HostPort
    account: Person

    # The language of the bot's messages: en, or one in nejomibot/locale
    language: str = "en"
    # Other names for commands, e.g. {"/photo": ["/pic", "pic"]}
    aliases: dict[Command, list[Alias]] = {}

    # Weather
    openweather_api_key: SecretStr
    weather_city: str
    # The city as the weather post names it; weather_city if not given
    weather_city_name: str | None = None
    weather_units: Literal["metric", "imperial"] = "metric"
    # /weather <city>: the most calls to OpenWeatherMap in an hour for places
    # named, finding them included. weather_city's weather, as in the daily
    # post, is asked at most every 10 minutes, and isn't counted.
    weather_calls_per_hour: Annotated[int, Field(ge=1)] = 10

    timezone: TimeZone = "Europe/Stockholm"

    photos_dir: Path = Path("/photos")
    # Where the bot keeps what it's been told and what it's done: the timers,
    # the specials, the allowed list and the photos sent this round. Only the
    # bot reads it.
    data_dir: Path = Path("/data")
    # Where photos that don't say their time zone were taken; timezone if not
    # given. Captions show the time in timezone, wherever a photo was taken.
    photos_timezone: TimeZone | None = None
    # With a birth date, captions show the age of who's in the photos
    photos_birth_date: date | None = None
    photos_age_emoji: str = "🎂"
    # Captions link to where a photo was taken on this map
    photos_map: Literal["google", "openstreetmap"] = "google"
    # HEIC and HEIF photos, sent as JPEG; without, they're left out, which
    # saves the 3 MB or so of memory it takes to open them
    photos_heif: bool = True

    # /info: the time in these places, by name, and an exchange rate
    clocks: dict[str, TimeZone] = {}  # none: the time in timezone
    exchange_rate: tuple[Currency, Currency] | None = None  # e.g. EUR, SEK

    # /fortune's library when none is named: one that /fortune list names, or
    # all of them. The default comes with the bot, so it isn't checked.
    fortune_library: str = Field("fortunes_svenska", validate_default=False)

    # Messages that couldn't be sent (Signal down, no internet) are tried
    # again for this long, then dropped
    send_retry_hours: PositiveFloat = 3

    # The admins: they may use every command, and they alone the admin
    # commands, in a direct chat with the bot
    admins: list[Person] = []

    # Every healthcheck_minutes the bot checks signal-cli-rest-api, itself, and
    # Signal's servers with its account (health.py). With a URL such as
    # https://hc-ping.com/<uuid>, it then pings it, or URL/fail, with what it
    # found, the versions, the uptime and its memory.
    healthcheck_url: (
        Annotated[str, StringConstraints(pattern=r"^https?://\S+$")] | None
    ) = None
    healthcheck_minutes: Annotated[int, Field(ge=1)] = 5

    # How much the bot logs: DEBUG adds what each command says and who sent
    # it, and whom messages go to; WARNING only what went wrong. Other
    # libraries log only what went wrong.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Debug mode: only talk to debug_group (and the admins), with an allowed
    # list of just that group and no timers at each start, and what the bot
    # keeps in temp files rather than data_dir.
    debug: bool = False
    debug_group: GroupId | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_settings = TomlConfigSettingsSource(settings_cls, toml_file=config_file())
        return init_settings, env_settings, toml_settings

    @field_validator("language")
    @classmethod
    def known_language(cls, value: str) -> str:
        from .i18n import languages  # which imports this module

        if value not in (known := languages()):
            raise ValueError(f"unknown language {value!r}, not one of {known}")
        return value

    @field_validator("fortune_library")
    @classmethod
    def known_fortune_library(cls, value: str) -> str:
        # Here, as fortune imports this module
        from .fortune import ALL, FORTUNES_DIR, fortune_libraries

        known = [path.name for path in fortune_libraries(FORTUNES_DIR)]
        if value != ALL and value not in known:
            raise ValueError(
                f"unknown fortune library {value!r}, not {ALL} or one of {known}"
            )
        return value

    @model_validator(mode="after")
    def debug_needs_group(self) -> Self:
        if self.debug and not self.debug_group:
            raise ValueError("debug mode needs debug_group")
        return self

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @cached_property
    def photos_tz(self) -> ZoneInfo:
        return ZoneInfo(self.photos_timezone or self.timezone)

    @property
    def clock_zones(self) -> dict[str, ZoneInfo]:
        """The places /info shows the time in, by name."""
        if not self.clocks:
            city = self.timezone.rsplit("/", 1)[-1].replace("_", " ")
            return {city: self.tz}
        return {name: ZoneInfo(zone) for name, zone in self.clocks.items()}

    @property
    def configured_recipients(self) -> list[str]:
        """The contacts and groups in the config the bot talks to; the allowed
        list has the rest (access.recipients has them all)."""
        return sorted(
            {
                *self.admins,
                *([self.debug_group] if self.debug_group else []),
            }
        )

    @property
    def delete_groups(self) -> list[str] | bool:
        """Groups an admin's /delete works in: all of them (True), except in
        debug mode."""
        return [self.debug_group] if self.debug and self.debug_group else True

    def data_file(self, name: str) -> Path:
        """A file in data_dir, or in debug mode in a temp folder of its own."""
        return (Path(debug_folder().name) if self.debug else self.data_dir) / name

    @property
    def sent_photos_file(self) -> Path:
        """Photos already sent in this round, one path per line."""
        return self.data_file("sent-photos.txt")

    @property
    def timers_file(self) -> Path:
        """The timers, one per line, so they survive restarts."""
        return self.data_file("timers.txt")

    @property
    def specials_file(self) -> Path:
        """The admins' own specials, one per line."""
        return self.data_file("specials.txt")

    @property
    def allowed_file(self) -> Path:
        """Who may use the everyday commands, besides the admins: one per line."""
        return self.data_file("allowed.txt")

    @property
    def outbox_dir(self) -> Path:
        """Messages waiting to be sent, a file each, so they survive restarts."""
        return self.data_file("outbox")


@cache
def debug_folder() -> tempfile.TemporaryDirectory[str]:
    """Where debug mode keeps its files: a private temp folder, new at each
    start and gone when the bot stops."""
    return tempfile.TemporaryDirectory(prefix="nejomibot-")


@cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from file/env
