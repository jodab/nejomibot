"""/weather: the weather now, from OpenWeatherMap, under a heading in bold.
Alone, in weather_city, which the heading names weather_city_name, if set;
with a place, as in /weather Helsinki, there, the heading naming the place
OpenWeatherMap found, in the bot's language if it has the name in it, with
its state or region and country: Weather in Springfield, Illinois, US.

OpenWeatherMap's geocoding finds places by name, the best known first (it
doesn't say so, but Stockholm is the one in Sweden, not Maine's), and the bot
takes the first; a misspelt name may find one too. A country code after a
comma picks the country, and in the US a state code the state: /weather
Stockholm,US, /weather Springfield,MO,US. The bot asks where a name is once,
as places don't move, then the weather there, as OpenWeatherMap no longer
develops its weather by city name.

It keeps each place's weather for 10 minutes, as OpenWeatherMap's changes
every 10 minutes, and answers with that when asked again sooner. About places
named, it asks OpenWeatherMap at most weather_calls_per_hour times an hour,
finding them included, and says when to try again past that. weather_city's
weather, as in the daily post, isn't counted, so it's never refused.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from time import monotonic
from typing import Any

import aiohttp
from signalbot import DataMessageContext

from .client import client
from .commands import Command, Handler, answer, argument
from .config import get_settings
from .i18n import N_, _, day_and_time, ngettext
from .messages import ServiceError, error_text, escape, log_failure, web_error
from .styles import bold

logger = logging.getLogger(__name__)

API_URL = "https://api.openweathermap.org/data/2.5/weather"
GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
TIMEOUT = aiohttp.ClientTimeout(total=15)
# Seconds a place's weather is kept, as OpenWeatherMap's changes every 10 minutes
FRESH = 10 * 60
HOUR = 60 * 60
MAX_PLACES = 100  # names whose place is kept, the oldest going first

# OpenWeatherMap's conditions by code (https://openweathermap.org/weather-conditions).
# A code missing here gets the description OpenWeatherMap gives, in the
# language it's asked for.
DESCRIPTIONS = {
    200: N_("thunderstorm with light rain"),
    201: N_("thunderstorm with rain"),
    202: N_("thunderstorm with heavy rain"),
    210: N_("light thunderstorm"),
    211: N_("thunderstorm"),
    212: N_("heavy thunderstorm"),
    221: N_("ragged thunderstorm"),
    230: N_("thunderstorm with light drizzle"),
    231: N_("thunderstorm with drizzle"),
    232: N_("thunderstorm with heavy drizzle"),
    300: N_("light drizzle"),
    301: N_("drizzle"),
    302: N_("heavy drizzle"),
    310: N_("light drizzle and rain"),
    311: N_("drizzle and rain"),
    312: N_("heavy drizzle and rain"),
    313: N_("shower rain and drizzle"),
    314: N_("heavy shower rain and drizzle"),
    321: N_("shower drizzle"),
    500: N_("light rain"),
    501: N_("moderate rain"),
    502: N_("heavy rain"),
    503: N_("very heavy rain"),
    504: N_("extreme rain"),
    511: N_("freezing rain"),
    520: N_("light shower rain"),
    521: N_("shower rain"),
    522: N_("heavy shower rain"),
    531: N_("ragged shower rain"),
    600: N_("light snow"),
    601: N_("snow"),
    602: N_("heavy snow"),
    611: N_("sleet"),
    612: N_("light shower sleet"),
    613: N_("shower sleet"),
    615: N_("light rain and snow"),
    616: N_("rain and snow"),
    620: N_("light shower snow"),
    621: N_("shower snow"),
    622: N_("heavy shower snow"),
    701: N_("mist"),
    711: N_("smoke"),
    721: N_("haze"),
    731: N_("sand and dust whirls"),
    741: N_("fog"),
    751: N_("sand"),
    761: N_("dust"),
    762: N_("volcanic ash"),
    771: N_("squalls"),
    781: N_("tornado"),
    800: N_("clear sky"),
    801: N_("few clouds"),
    802: N_("scattered clouds"),
    803: N_("broken clouds"),
    804: N_("overcast clouds"),
}
CLOUD_ICONS = {800: "☀️", 801: "🌤️", 802: "⛅️", 803: "☁️", 804: "☁️"}
DEFAULT_ICON = "🌡️"
UNITS = {"metric": "°C", "imperial": "°F"}


class WeatherError(ServiceError):
    """The weather can't be had."""


class NoPlace(WeatherError):
    """OpenWeatherMap knows no place by the name."""


class TooOften(WeatherError):
    """The past hour has had weather_calls_per_hour calls for places named."""


def condition_icon(code: int) -> str:
    """By the condition's group: thunderstorm, drizzle, rain, snow, atmosphere
    (mist, haze...), clear or clouds."""
    if 200 <= code < 300:
        return "⛈️"
    if 300 <= code < 400 or code in (500, 520):
        return "🌦️"
    if 500 <= code < 600:
        return "🌧️"
    if code in (600, 620) or 611 <= code < 620:
        return "🌨️"
    if 600 <= code < 700:
        return "❄️"
    if code == 781:
        return "🌪️"
    if 700 <= code < 800:
        return "🌫️"
    return CLOUD_ICONS.get(code, DEFAULT_ICON)


def temperature_icon(celsius: float) -> str:
    if celsius < 0:
        return "🥶"
    if celsius < 10:
        return "❄️"
    if celsius < 20:
        return "🌡️"
    if celsius < 30:
        return "☀️"
    return "🥵"


def humidity_icon(humidity: int) -> str:
    return "🏜️" if humidity < 30 else "💧"


def format_weather(
    data: dict[str, Any], city: str, now: datetime, units: str = "metric"
) -> str:
    """Styled."""
    try:
        condition = data["weather"][0]
        code = int(condition["id"])
        given = str(condition.get("description") or "")
        temp = round(data["main"]["temp"])
        feels_like = round(data["main"]["feels_like"])
        humidity = data["main"]["humidity"]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        raise WeatherError(_("the weather data isn't as expected")) from e

    known = DESCRIPTIONS.get(code)
    description = (_(known) if known else given or _("unknown weather")).capitalize()
    unit = UNITS.get(units, "°")
    celsius = temp if units == "metric" else (temp - 32) * 5 / 9
    heading = _("Weather in {city}").format(city=city)
    lines = [
        day_and_time(now),
        f"{condition_icon(code)} {description}",
        _("{icon} Temperature: {temperature}").format(
            icon=temperature_icon(celsius), temperature=f"{temp}{unit}"
        ),
        _("🤔 Feels like: {temperature}").format(temperature=f"{feels_like}{unit}"),
        _("{icon} Humidity: {humidity}").format(
            icon=humidity_icon(humidity), humidity=f"{humidity}%"
        ),
    ]
    return f"{bold(heading)}\n" + escape("\n".join(lines))


# When OpenWeatherMap was asked about places named, in the past hour
calls: deque[float] = deque()


def count_call() -> None:
    """Count a call for a place named, unless the past hour has had
    weather_calls_per_hour of them: then raise TooOften, saying when the
    first of them is an hour old."""
    now = monotonic()
    while calls and now - calls[0] >= HOUR:
        calls.popleft()
    limit = get_settings().weather_calls_per_hour
    if len(calls) >= limit:
        minutes = ceil((calls[0] + HOUR - now) / 60)
        raise TooOften(
            ngettext(
                "⏳ The bot asks OpenWeatherMap about places at most {count} time "
                "an hour.",
                "⏳ The bot asks OpenWeatherMap about places at most {count} times "
                "an hour.",
                limit,
            ).format(count=limit)
            + " "
            + ngettext(
                "Try again in {minutes} minute.",
                "Try again in {minutes} minutes.",
                minutes,
            ).format(minutes=minutes)
        )
    calls.append(now)


async def ask(url: str, *, counted: bool = False, **params: str) -> Any:
    """OpenWeatherMap's answer; a call counted is one for a place named (see
    count_call). Raises WeatherError."""
    if counted:
        count_call()
    params["appid"] = get_settings().openweather_api_key.get_secret_value()
    try:
        async with client.session().get(
            url, params=params, timeout=TIMEOUT
        ) as response:
            try:
                data: Any = await response.json(content_type=None)
            except ValueError as e:
                raise WeatherError(_("the weather data can't be read")) from e
            if response.status != 200:
                detail = data.get("message") if isinstance(data, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                error = f"{response.status}: {detail}" if detail else response.status
                raise WeatherError(
                    _("OpenWeatherMap answered with an error ({error})").format(
                        error=error
                    )
                )
            return data
    except (aiohttp.ClientError, TimeoutError) as e:
        raise WeatherError(
            _("OpenWeatherMap can't be reached: {error}").format(error=web_error(e))
        ) from e


@dataclass(frozen=True)
class Place:
    """Where a place is, and its name, as OpenWeatherMap's geocoding has them."""

    lat: str
    lon: str
    name: str  # e.g. 'Springfield, Illinois, US'


# Where places are, by the name asked, in lower case
places: dict[str, Place] = {}


async def place(city: str, *, counted: bool = False) -> Place:
    """Where the city is, from OpenWeatherMap's geocoding, which takes the
    name as its weather by name did: Stockholm, or Stockholm,SE. Its first
    place of the name, named in the bot's language if it has that, with its
    state and country. Raises WeatherError."""
    key = city.casefold()
    if key not in places:
        found = await ask(GEOCODING_URL, counted=counted, q=city, limit="1")
        try:
            first = found[0]
            lat, lon = str(float(first["lat"])), str(float(first["lon"]))
            names: Any = first.get("local_names") or {}
            name = names.get(get_settings().language) or first.get("name") or city
            parts = [name, first.get("state"), first.get("country")]
        except (IndexError, KeyError, TypeError, ValueError, AttributeError) as e:
            raise NoPlace(
                _("OpenWeatherMap knows no place called {city}").format(city=city)
            ) from e
        if len(places) >= MAX_PLACES:
            del places[next(iter(places))]
        places[key] = Place(lat, lon, ", ".join(str(part) for part in parts if part))
    return places[key]


# Each place's latest weather, by where it is, and when it came
latest: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


async def fetch_weather(city: str = "") -> tuple[Place, dict[str, Any]]:
    """The weather in the city named, else in weather_city, and where that
    is: what the bot got in the last 10 minutes, or else asked anew, which is
    counted for a city named. Raises WeatherError."""
    settings = get_settings()
    where = await place(city or settings.weather_city, counted=bool(city))
    now = monotonic()
    for old in [key for key, (at, _data) in latest.items() if now - at >= FRESH]:
        del latest[old]
    key = (where.lat, where.lon)
    if key not in latest:
        data = await ask(
            API_URL,
            counted=bool(city),
            lat=where.lat,
            lon=where.lon,
            units=settings.weather_units,
            lang=settings.language,
        )
        latest[key] = (monotonic(), data)
    return where, latest[key][1]


async def weather_message(city: str = "") -> str:
    """The weather in the city named, else in weather_city; or why it can't
    be had. Styled."""
    settings = get_settings()
    try:
        where, data = await fetch_weather(city)
        configured = settings.weather_city_name or settings.weather_city
        return format_weather(
            data,
            where.name if city else configured,
            datetime.now(settings.tz),
            settings.weather_units,
        )
    except TooOften as e:
        logger.info("The weather: weather_calls_per_hour reached for places named")
        return escape(str(e))
    except Exception as e:
        # A name that's no place is no failure, and what follows a command is
        # for DEBUG alone
        if not (city and isinstance(e, NoPlace)):
            log_failure(logger, "The weather", e)
        return escape(error_text(e))


class Weather(Handler):
    commands = (Command("/weather", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        city = argument(context.message.text)
        await answer(context, lambda: weather_message(city), slow=True, styled=True)
