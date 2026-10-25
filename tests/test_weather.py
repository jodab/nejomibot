import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from aiohttp import web
from helpers import ALICE, Clock
from signalbot import DataMessage, DataMessageContext, SendMessage, SignalBot

from nejomibot import commands, receipts, weather
from nejomibot.config import get_settings

TZ = ZoneInfo("Europe/Stockholm")

# In Swedish, as the bot has always posted it
pytestmark = pytest.mark.usefixtures("swedish")


def api_data(
    code: int, description: str, temp: float, feels_like: float, humidity: int
) -> Any:
    return {
        "weather": [{"id": code, "description": description}],
        "main": {"temp": temp, "feels_like": feels_like, "humidity": humidity},
    }


def test_format_weather() -> None:
    data = api_data(804, "mulet", 23.6, 24.4, 77)
    # The heading in bold
    assert weather.format_weather(data, "Göteborg") == (
        "**Vädret i Göteborg**\n"
        "☁️ Mulet\n"
        "☀️ Temperatur: 24°C\n"
        "🤔 Känns som: 24°C\n"
        "💧 Luftfuktighet: 77%"
    )


@pytest.mark.parametrize(
    ("code", "line"),
    [
        (721, "🌫️ Dis"),
        (502, "🌧️ Kraftigt regn"),
        (500, "🌦️ Lätt regn"),
        (600, "🌨️ Lätt snöfall"),
        (781, "🌪️ Tornado"),
        (212, "⛈️ Kraftig åska"),
    ],
)
def test_format_weather_in_swedish(code: int, line: str) -> None:
    data = api_data(code, "in English", 20, 20, 50)
    assert weather.format_weather(data, "Göteborg").splitlines()[1] == line


def test_format_weather_unknown_condition() -> None:
    data = api_data(999, "vulkanisk aska", -3.2, -8, 20)
    assert weather.format_weather(data, "Stockholm").splitlines() == [
        "**Vädret i Stockholm**",
        "🌡️ Vulkanisk aska",
        "🥶 Temperatur: -3°C",
        "🤔 Känns som: -8°C",
        "🏜️ Luftfuktighet: 20%",
    ]


def test_format_weather_in_fahrenheit() -> None:
    data = api_data(800, "klar himmel", 75.2, 80, 40)
    assert weather.format_weather(data, "Göteborg", "imperial").splitlines()[1:4] == [
        "☀️ Klar himmel",
        "☀️ Temperatur: 75°F",  # 24°C
        "🤔 Känns som: 80°F",
    ]


def test_format_weather_escapes() -> None:
    # As it shows, the city as the config has it, the condition as given
    data = api_data(999, "*sunny* ~ish", 20, 20, 50)
    assert weather.format_weather(data, "Sthlm`").splitlines()[0:2] == [
        "**Vädret i Sthlm\\`**",
        "🌡️ \\*sunny\\* \\~ish",
    ]


def test_format_weather_bad_data() -> None:
    with pytest.raises(weather.WeatherError, match="inte ut som väntat"):
        weather.format_weather({"main": {}}, "Göteborg")


def test_format_weather_in_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", "en")
    get_settings.cache_clear()
    data = api_data(804, "overcast clouds", 23.6, 24.4, 77)
    assert weather.format_weather(data, "London") == (
        "**Weather in London**\n"
        "☁️ Overcast clouds\n"
        "☀️ Temperature: 24°C\n"
        "🤔 Feels like: 24°C\n"
        "💧 Humidity: 77%"
    )


STOCKHOLM = [
    {"name": "Stockholm", "lat": 59.3251172, "lon": 18.0710935, "country": "SE"}
]
# As OpenWeatherMap's geocoding has them: one with a name in Swedish, one
# with a state
GOTHENBURG = [
    {
        "name": "Gothenburg",
        "local_names": {"sv": "Göteborg", "en": "Gothenburg"},
        "lat": 57.7072326,
        "lon": 11.9670171,
        "country": "SE",
    }
]
SPRINGFIELD = [
    {
        "name": "Springfield",
        "local_names": {"en": "Springfield"},
        "lat": 39.7990175,
        "lon": -89.6439575,
        "country": "US",
        "state": "Illinois",
    }
]
WEATHER = json.dumps(
    {"weather": [{"id": 800}], "main": {"temp": 1, "feels_like": 1, "humidity": 1}}
)
SUMMER = timezone(timedelta(hours=2))  # Stockholm's in October, till the 25th


def step(at: str, temperature: float, code: int, rain: float = 0) -> Any:
    """Three hours of OpenWeatherMap's forecast, from at, in Stockholm."""
    start = datetime.fromisoformat(at).replace(tzinfo=SUMMER)
    return {
        "dt": int(start.timestamp()),
        "main": {"temp": temperature},
        "weather": [{"id": code, "description": "in English"}],
        "pop": rain,
    }


FORECAST: Any = {
    "city": {"timezone": 7200},
    "list": [
        step("2026-10-19 14:00", 12.4, 500, 0.8),
        step("2026-10-19 17:00", 10, 804, 0.3),
        step("2026-10-19 20:00", 8, 800),
        step("2026-10-19 23:00", 6, 800),
        step("2026-10-20 02:00", 4, 600, 0.9),  # at night: not the day's weather
        step("2026-10-20 05:00", 3, 801),
        step("2026-10-20 08:00", 7, 802),
        step("2026-10-20 11:00", 11, 803, 0.24),
        step("2026-10-20 14:00", 12, 804),
        step("2026-10-20 17:00", 9, 803),
        step("2026-10-20 20:00", 6, 801),
        step("2026-10-20 23:00", 5, 800),
        step("2026-10-21 02:00", -1.6, 800),
        step("2026-10-21 08:00", 0, 600, 0.04),
        step("2026-10-21 14:00", 2, 803),
    ],
}


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    """A local stand-in for OpenWeatherMap; set 'status' and 'body' per test,
    and 'places' for its geocoding, by the name asked. What it was asked goes
    in 'asked'."""
    reply: dict[str, Any] = {
        "status": 200,
        "body": "{}",
        "places": {"Stockholm": STOCKHOLM},
    }
    reply["asked"] = asked = list[tuple[str, dict[str, str]]]()

    async def handler(request: web.Request) -> web.Response:
        asked.append((request.path, dict(request.query)))
        reply["query"] = dict(request.query)
        return web.Response(status=reply["status"], text=reply["body"])

    async def loop(request: web.Request) -> web.Response:
        raise web.HTTPFound(request.path_qs)

    async def geocoding(request: web.Request) -> web.Response:
        asked.append((request.path, dict(request.query)))
        return web.json_response(reply["places"].get(request.query["q"], []))

    async def forecast(request: web.Request) -> web.Response:
        asked.append((request.path, dict(request.query)))
        return web.json_response(reply.get("forecast", FORECAST))

    app = web.Application()
    app.router.add_get("/weather", handler)
    app.router.add_get("/forecast", forecast)
    app.router.add_get("/direct", geocoding)
    app.router.add_get("/loop", loop)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    port = runner.addresses[0][1]
    monkeypatch.setattr(weather, "API_URL", f"http://127.0.0.1:{port}/weather")
    monkeypatch.setattr(weather, "FORECAST_URL", f"http://127.0.0.1:{port}/forecast")
    monkeypatch.setattr(weather, "GEOCODING_URL", f"http://127.0.0.1:{port}/direct")
    yield reply
    await runner.cleanup()


def paths(api: dict[str, Any]) -> list[str]:
    """What OpenWeatherMap was asked: /direct where a place is, /weather its
    weather."""
    return [path for path, _query in api["asked"]]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The weather kept and the calls counted, on a clock of the test's own."""
    clock = Clock()
    monkeypatch.setattr(weather, "monotonic", clock)
    return clock


async def test_weather_message(api: dict[str, Any]) -> None:
    api["body"] = (
        '{"weather": [{"id": 501, "description": "måttligt regn"}],'
        ' "main": {"temp": 9.5, "feels_like": 7, "humidity": 90}}'
    )
    lines = (await weather.weather_message()).splitlines()
    # Without the date and the time, which /today has
    assert lines == [
        "**Vädret i Stockholm**",
        "🌧️ Måttligt regn",
        "🌡️ Temperatur: 10°C",
        "🤔 Känns som: 7°C",
        "💧 Luftfuktighet: 90%",
    ]
    # By where the city is, which OpenWeatherMap's geocoding says
    assert api["asked"] == [
        ("/direct", {"q": "Stockholm", "limit": "1", "appid": "test-key"}),
        (
            "/weather",
            {
                "lat": "59.3251172",
                "lon": "18.0710935",
                "units": "metric",
                "lang": "sv",
                "appid": "test-key",
            },
        ),
    ]


async def test_the_weather_is_kept_for_10_minutes(
    api: dict[str, Any], clock: Clock
) -> None:
    api["body"] = WEATHER
    await weather.weather_message()
    clock.now += 599
    await weather.weather_message()
    clock.now += 1
    await weather.weather_message()
    # Where the city is, once, as places don't move
    assert paths(api) == ["/direct", "/weather", "/weather"]


async def test_an_unknown_city(
    api: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    api["places"] = {}
    assert await weather.weather_message() == (
        "Något gick fel: OpenWeatherMap känner inte till någon plats som heter "
        "Stockholm"
    )
    # weather_city is the config's, so it's a failure
    assert "The weather failed" in caplog.text
    assert paths(api) == ["/direct"]


async def test_weather_message_names_the_city(
    api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_WEATHER_CITY_NAME", "Sthlm")
    get_settings.cache_clear()
    api["body"] = WEATHER
    assert (await weather.weather_message()).startswith("**Vädret i Sthlm**\n")
    assert api["asked"][0][1]["q"] == "Stockholm"


async def test_a_city_named(api: dict[str, Any]) -> None:
    api["body"] = WEATHER
    api["places"] = {"Springfield,IL,US": SPRINGFIELD}
    lines = (await weather.weather_message("Springfield,IL,US")).splitlines()
    # As found: with its state and country, and no name in Swedish
    assert lines[0] == "**Vädret i Springfield, Illinois, US**"
    assert api["asked"] == [
        ("/direct", {"q": "Springfield,IL,US", "limit": "1", "appid": "test-key"}),
        (
            "/weather",
            {
                "lat": "39.7990175",
                "lon": "-89.6439575",
                "units": "metric",
                "lang": "sv",
                "appid": "test-key",
            },
        ),
    ]


async def test_a_city_named_by_its_name_in_the_language(api: dict[str, Any]) -> None:
    api["body"] = WEATHER
    api["places"] = {"Gothenburg": GOTHENBURG}
    message = await weather.weather_message("Gothenburg")
    assert message.startswith("**Vädret i Göteborg, SE**\n")


async def test_a_city_named_is_found_once_in_any_case(api: dict[str, Any]) -> None:
    api["body"] = WEATHER
    api["places"] = {"Göteborg": GOTHENBURG}
    await weather.weather_message("Göteborg")
    await weather.weather_message("GÖTEBORG")
    assert paths(api) == ["/direct", "/weather"]


async def test_a_city_named_shares_the_weather_of_its_place(
    api: dict[str, Any],
) -> None:
    api["body"] = WEATHER
    api["places"] = {"Stockholm": STOCKHOLM, "Sthlm": STOCKHOLM}
    await weather.weather_message()
    message = await weather.weather_message("Sthlm")
    assert message.startswith("**Vädret i Stockholm, SE**\n")
    # Sthlm is where Stockholm is, whose weather the bot has
    assert paths(api) == ["/direct", "/weather", "/direct"]


async def test_a_city_named_that_isnt_one(
    api: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="nejomibot")
    assert await weather.weather_message("Nowhere") == (
        "Något gick fel: OpenWeatherMap känner inte till någon plats som heter Nowhere"
    )
    # No failure, and what follows the command is message text: not logged
    assert "Nowhere" not in caplog.text


async def test_places_named_are_asked_about_so_often_an_hour(
    api: dict[str, Any],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("NEJOMIBOT_WEATHER_CALLS_PER_HOUR", "3")
    get_settings.cache_clear()
    caplog.set_level(logging.INFO, logger="nejomibot")
    api["body"] = WEATHER
    api["places"] |= {"Springfield": SPRINGFIELD, "Göteborg": GOTHENBURG}
    # Two calls: where Springfield is, and its weather
    message = await weather.weather_message("Springfield")
    assert message.startswith("**Vädret i Springfield")
    clock.now += 60
    # Where Göteborg is is the third call; its weather would be a fourth
    assert await weather.weather_message("Göteborg") == (
        "⏳ Boten frågar OpenWeatherMap om platser högst 3 gånger i timmen. "
        "Försök igen om 59 minuter."
    )
    assert "weather_calls_per_hour reached" in caplog.text
    # The weather kept takes no call, and weather_city's calls aren't counted
    assert (await weather.weather_message("Springfield")).startswith("**Vädret i S")
    assert (await weather.weather_message()).startswith("**Vädret i Stockholm**")
    # An hour after the first two
    clock.now += 59 * 60
    message = await weather.weather_message("Göteborg")
    assert message.startswith("**Vädret i Göteborg, SE**")
    assert paths(api) == [
        "/direct",
        "/weather",
        "/direct",
        "/direct",
        "/weather",
        "/weather",
    ]


async def test_one_call_an_hour(
    api: dict[str, Any], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_WEATHER_CALLS_PER_HOUR", "1")
    get_settings.cache_clear()
    api["places"] = {"Göteborg": GOTHENBURG}
    # Finding Göteborg is the hour's one call
    message = await weather.weather_message("Göteborg")
    assert message.endswith("Försök igen om 60 minuter.")
    clock.now += 3599
    assert await weather.weather_message("Göteborg") == (
        "⏳ Boten frågar OpenWeatherMap om platser högst 1 gång i timmen. "
        "Försök igen om 1 minut."
    )
    assert paths(api) == ["/direct"]


async def test_the_command(
    api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    api["body"] = WEATHER
    api["places"] = {"Stockholm": STOCKHOLM, "Göteborg": GOTHENBURG}
    replies: list[str] = []

    async def nothing(context: DataMessageContext) -> None:
        pass

    async def reply(context: DataMessageContext, message: SendMessage) -> None:
        replies.append(message.text or "")

    monkeypatch.setattr(commands, "mark_read", nothing)
    monkeypatch.setattr(receipts, "show_typing", nothing)
    monkeypatch.setattr(receipts, "stop_typing", nothing)
    monkeypatch.setattr(commands, "reply", reply)
    # By its Swedish name too, and with the place's spaces made single
    for text in ["/väder  Göteborg", "/weather"]:
        message = DataMessage(
            server_delivered_timestamp=0,
            server_received_timestamp=0,
            timestamp=0,
            source_number=ALICE,
            text=text,
        )
        context = DataMessageContext(cast(SignalBot, None), message)
        await weather.Weather().handle_data_message(context)
    assert [text.splitlines()[0] for text in replies] == [
        "**Vädret i Göteborg, SE**",
        "**Vädret i Stockholm**",
    ]
    assert api["asked"][0][1]["q"] == "Göteborg"


async def test_weather_message_api_error(api: dict[str, Any]) -> None:
    api["status"], api["body"] = 401, '{"message": "Invalid API key"}'
    assert await weather.weather_message() == (
        "Något gick fel: OpenWeatherMap svarade med ett fel (401: Invalid API key)"
    )


async def test_weather_message_bad_json(api: dict[str, Any]) -> None:
    api["body"] = "<html>"
    assert await weather.weather_message() == (
        "Något gick fel: väderdatan går inte att läsa"
    )


async def test_weather_message_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather, "GEOCODING_URL", "http://127.0.0.1:1/direct")
    message = await weather.weather_message()
    assert message.startswith("Något gick fel: OpenWeatherMap går inte att nå: ")


async def test_the_key_stays_out_of_errors(
    api: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # aiohttp's text for some errors has the URL, and in it the key
    loop = weather.API_URL.replace("/weather", "/loop")
    monkeypatch.setattr(weather, "API_URL", loop)
    assert await weather.weather_message() == (
        "Något gick fel: OpenWeatherMap går inte att nå: TooManyRedirects"
    )

    class Session:
        def get(self, *args: object, **kwargs: object) -> Any:
            raise aiohttp.ConnectionTimeoutError(
                f"Connection timeout to host {loop}?appid=test-key"
            )

    monkeypatch.setattr(weather.client, "session", Session)
    assert await weather.weather_message() == (
        "Något gick fel: OpenWeatherMap går inte att nå: ConnectionTimeoutError"
    )
    assert "test-key" not in caplog.text


# Sunrise and sunset


def at_utc(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp())


def with_sun(data: Any, zone: int) -> Any:
    sun = {"sunrise": at_utc("2026-10-19 05:35"), "sunset": at_utc("2026-10-19 15:21")}
    return data | {"timezone": zone, "sys": sun}


def test_the_sun() -> None:
    data = with_sun(api_data(804, "mulet", 9, 7, 80), 7200)
    lines = weather.format_weather(data, "Stockholm").splitlines()
    assert lines[-1] == "🌅 07:35 · 🌇 17:21 · 9 tim 46 min dagsljus"
    # In the place's time
    data = with_sun(api_data(804, "mulet", 9, 7, 80), 10800)
    lines = weather.format_weather(data, "Helsingfors").splitlines()
    assert lines[-1] == "🌅 08:35 · 🌇 18:21 · 9 tim 46 min dagsljus"


@pytest.mark.parametrize(
    "sun",
    [
        {},  # not said
        {"sys": {"sunrise": 0, "sunset": 0}, "timezone": 0},  # polar night or day
        {"sys": {"sunrise": "soon"}, "timezone": 0},
    ],
)
def test_no_sun(sun: Any) -> None:
    data = api_data(804, "mulet", 9, 7, 80) | sun
    assert len(weather.format_weather(data, "Kiruna").splitlines()) == 5


# The forecast


def test_format_forecast() -> None:
    steps = weather.forecast_steps(FORECAST)
    now = datetime(2026, 10, 19, 13, 30, tzinfo=SUMMER)
    # Each day's worst weather from 06:00 to 21:00, its lowest and highest
    # temperature, and its highest chance of rain or snow, if any
    assert weather.format_forecast(steps, "Stockholm", now) == "\n".join(
        [
            "**Prognos för Stockholm**",
            "Idag: 🌦️ Lätt regn",
            "🌡️ 6 till 12°C · ☔ 80%",
            "Imorgon: ☁️ Mulet",
            "🌡️ 3 till 12°C · ☔ 90%",
        ]
    )


def test_a_forecast_kept_past_midnight() -> None:
    # Kept from the evening before: yesterday's steps aren't a day of it
    steps = weather.forecast_steps(FORECAST)
    now = datetime(2026, 10, 20, 0, 10, tzinfo=SUMMER)
    assert weather.format_forecast(steps, "Stockholm", now).splitlines()[1] == (
        "Idag: ☁️ Mulet"
    )


def test_late_in_the_evening_the_day_after() -> None:
    # Today has no daytime left: tomorrow and the day after
    steps = weather.forecast_steps(FORECAST)[3:]
    now = datetime(2026, 10, 19, 22, 30, tzinfo=SUMMER)
    assert weather.format_forecast(steps, "Stockholm", now).splitlines()[1:] == [
        "Imorgon: ☁️ Mulet",
        "🌡️ 3 till 12°C · ☔ 90%",
        "Onsdag: 🌨️ Lätt snöfall",
        "🌡️ -2 till 2°C",
    ]


NOT_AS_EXPECTED: list[Any] = [
    {},
    {"city": {"timezone": 0}, "list": []},
    {"city": {}, "list": [{}]},
]


@pytest.mark.parametrize("data", NOT_AS_EXPECTED)
def test_forecast_data_not_as_expected(data: Any) -> None:
    with pytest.raises(weather.WeatherError, match="prognosdatan"):
        weather.forecast_steps(data)


async def test_the_forecast_is_kept_for_30_minutes(
    api: dict[str, Any], clock: Clock
) -> None:
    message = await weather.forecast_message()
    assert message.startswith("**Prognos för Stockholm**\n")
    clock.now += 30 * 60 - 1
    await weather.forecast_message()
    clock.now += 1
    await weather.forecast_message()
    assert paths(api) == ["/direct", "/forecast", "/forecast"]
    # Three days of three hours
    assert api["asked"][1][1] == {
        "lat": "59.3251172",
        "lon": "18.0710935",
        "units": "metric",
        "lang": "sv",
        "cnt": "24",
        "appid": "test-key",
    }


async def test_a_forecast_for_a_place_named_is_counted(
    api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_WEATHER_CALLS_PER_HOUR", "1")
    get_settings.cache_clear()
    api["places"] |= {"Göteborg": GOTHENBURG}
    # Finding Göteborg is the hour's one call
    assert (await weather.forecast_message("Göteborg")).startswith(
        "⏳ Boten frågar OpenWeatherMap om platser högst 1 gång i timmen."
    )
    # weather_city's isn't counted
    assert (await weather.forecast_message()).startswith("**Prognos för Stockholm**")


async def test_the_forecast_command(
    api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    api["places"] = {"Göteborg": GOTHENBURG}
    replies: list[str] = []

    async def nothing(context: DataMessageContext) -> None:
        pass

    async def reply(context: DataMessageContext, message: SendMessage) -> None:
        replies.append(message.text or "")

    monkeypatch.setattr(commands, "mark_read", nothing)
    monkeypatch.setattr(receipts, "show_typing", nothing)
    monkeypatch.setattr(receipts, "stop_typing", nothing)
    monkeypatch.setattr(commands, "reply", reply)
    message = DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=0,
        source_number=ALICE,
        text="/prognos Göteborg",
    )
    context = DataMessageContext(cast(SignalBot, None), message)
    await weather.Forecast().handle_data_message(context)
    [answer] = replies
    assert answer.startswith("**Prognos för Göteborg, SE**\n")
