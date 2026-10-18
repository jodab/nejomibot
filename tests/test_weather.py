import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from aiohttp import web

from nejomibot import weather
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
    now = datetime(2026, 10, 11, 15, 30, tzinfo=TZ)
    assert weather.format_weather(data, "Göteborg", now) == (
        "Vädret i Göteborg\n"
        "Söndag 11 Oktober 15:30\n"
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
    now = datetime(2026, 10, 11, 15, 30, tzinfo=TZ)
    assert weather.format_weather(data, "Göteborg", now).splitlines()[2] == line


def test_format_weather_unknown_condition() -> None:
    data = api_data(999, "vulkanisk aska", -3.2, -8, 20)
    now = datetime(2027, 1, 4, 8, 0, tzinfo=TZ)
    assert weather.format_weather(data, "Stockholm", now).splitlines() == [
        "Vädret i Stockholm",
        "Måndag 4 Januari 08:00",
        "🌡️ Vulkanisk aska",
        "🥶 Temperatur: -3°C",
        "🤔 Känns som: -8°C",
        "🏜️ Luftfuktighet: 20%",
    ]


def test_format_weather_in_fahrenheit() -> None:
    data = api_data(800, "klar himmel", 75.2, 80, 40)
    now = datetime(2026, 10, 11, 15, 30, tzinfo=TZ)
    assert weather.format_weather(data, "Göteborg", now, "imperial").splitlines()[
        2:5
    ] == [
        "☀️ Klar himmel",
        "☀️ Temperatur: 75°F",  # 24°C
        "🤔 Känns som: 80°F",
    ]


def test_format_weather_bad_data() -> None:
    with pytest.raises(weather.WeatherError, match="inte ut som väntat"):
        weather.format_weather({"main": {}}, "Göteborg", datetime.now(TZ))


def test_format_weather_in_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", "en")
    get_settings.cache_clear()
    data = api_data(804, "overcast clouds", 23.6, 24.4, 77)
    now = datetime(2026, 10, 11, 15, 30, tzinfo=TZ)
    assert weather.format_weather(data, "London", now) == (
        "Weather in London\n"
        "Sunday 11 October 15:30\n"
        "☁️ Overcast clouds\n"
        "☀️ Temperature: 24°C\n"
        "🤔 Feels like: 24°C\n"
        "💧 Humidity: 77%"
    )


STOCKHOLM = [{"name": "Stockholm", "lat": 59.3251172, "lon": 18.0710935}]


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    """A local stand-in for OpenWeatherMap; set 'status' and 'body' per test,
    and 'places' for its geocoding. What it was asked goes in 'asked'."""
    reply: dict[str, Any] = {"status": 200, "body": "{}", "places": STOCKHOLM}
    reply["asked"] = asked = list[tuple[str, dict[str, str]]]()

    async def handler(request: web.Request) -> web.Response:
        asked.append((request.path, dict(request.query)))
        reply["query"] = dict(request.query)
        return web.Response(status=reply["status"], text=reply["body"])

    async def loop(request: web.Request) -> web.Response:
        raise web.HTTPFound(request.path_qs)

    async def geocoding(request: web.Request) -> web.Response:
        asked.append((request.path, dict(request.query)))
        return web.json_response(reply["places"])

    app = web.Application()
    app.router.add_get("/weather", handler)
    app.router.add_get("/direct", geocoding)
    app.router.add_get("/loop", loop)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    port = runner.addresses[0][1]
    monkeypatch.setattr(weather, "API_URL", f"http://127.0.0.1:{port}/weather")
    monkeypatch.setattr(weather, "GEOCODING_URL", f"http://127.0.0.1:{port}/direct")
    monkeypatch.setattr(weather, "places", {})
    yield reply
    await runner.cleanup()


async def test_weather_message(api: dict[str, Any]) -> None:
    api["body"] = (
        '{"weather": [{"id": 501, "description": "måttligt regn"}],'
        ' "main": {"temp": 9.5, "feels_like": 7, "humidity": 90}}'
    )
    lines = (await weather.weather_message()).splitlines()
    assert lines[0] == "Vädret i Stockholm"
    assert lines[2:] == [
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


async def test_the_city_is_looked_up_once(api: dict[str, Any]) -> None:
    api["body"] = json.dumps(
        {"weather": [{"id": 800}], "main": {"temp": 1, "feels_like": 1, "humidity": 1}}
    )
    await weather.weather_message()
    await weather.weather_message()
    assert [path for path, _query in api["asked"]] == [
        "/direct",
        "/weather",
        "/weather",
    ]


async def test_an_unknown_city(api: dict[str, Any]) -> None:
    api["places"] = []
    assert await weather.weather_message() == (
        "Något gick fel: OpenWeatherMap känner inte till någon plats som heter "
        "Stockholm"
    )
    assert [path for path, _query in api["asked"]] == ["/direct"]


async def test_weather_message_names_the_city(
    api: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_WEATHER_CITY_NAME", "Sthlm")
    get_settings.cache_clear()
    api["body"] = json.dumps(
        {"weather": [{"id": 800}], "main": {"temp": 1, "feels_like": 1, "humidity": 1}}
    )
    assert (await weather.weather_message()).startswith("Vädret i Sthlm\n")
    assert api["asked"][0][1]["q"] == "Stockholm"


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
