"""/weather: the weather now, from OpenWeatherMap, under a heading in bold.
Alone, in weather_city, which the heading names weather_city_name, if set;
with a place, as in /weather Helsinki, there, the heading naming the place
OpenWeatherMap found, in the bot's language if it has the name in it, with
its state or region and country: Weather in Springfield, Illinois, US. It
ends with the day's sunrise, sunset and daylight there, in its time.

/forecast, alone or with a place as /weather takes it: the weather today and
tomorrow, from OpenWeatherMap's forecast for every three hours. For each
day, the worst weather from 06:00 to 21:00 there, the lowest and highest
temperature, and the highest chance of rain or snow. Late in the evening,
tomorrow and the day after.

OpenWeatherMap's geocoding finds places by name, the best known first (it
doesn't say so, but Stockholm is the one in Sweden, not Maine's), and the bot
takes the first; a misspelt name may find one too. A country code after a
comma picks the country, and in the US a state code the state: /weather
Stockholm,US, /weather Springfield,MO,US. The bot asks where a name is once,
as places don't move, then the weather there, as OpenWeatherMap no longer
develops its weather by city name.

It keeps each place's weather for 10 minutes, as OpenWeatherMap's changes
every 10 minutes, and its forecast for 30, and answers with those when asked
again sooner. About places named, it asks OpenWeatherMap at most
weather_calls_per_hour times an hour, finding them included, and says when to
try again past that. weather_city's weather and forecast, as in /today,
aren't counted, so they're never refused.
"""

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import ceil
from time import monotonic
from typing import Any

import aiohttp
from signalbot import DataMessageContext

from .client import client
from .commands import Command, Handler, answer, argument
from .config import get_settings
from .i18n import N_, _, day_and_time, format_duration, ngettext, weekday_name
from .messages import ServiceError, error_text, escape, log_failure, web_error
from .styles import bold

logger = logging.getLogger(__name__)

API_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
TIMEOUT = aiohttp.ClientTimeout(total=15)
# Seconds a place's weather is kept, as OpenWeatherMap's changes every 10 minutes
FRESH = 10 * 60
# Seconds a forecast is kept: OpenWeatherMap's are for every three hours
FORECAST_FRESH = 30 * 60
# The forecast's three-hour steps the bot asks for: three days' worth, enough
# for today and tomorrow, or late in the evening, tomorrow and the day after
FORECAST_STEPS = 24
# Hours of the day whose weather a day's forecast shows, the worst of them
DAYTIME = range(6, 22)
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


def described(code: int, given: str) -> str:
    """The condition in the bot's language: as the bot words it, else as
    OpenWeatherMap does."""
    known = DESCRIPTIONS.get(code)
    return (_(known) if known else given or _("unknown weather")).capitalize()


def sun_line(data: dict[str, Any]) -> str | None:
    """Sunrise, sunset and the daylight between, at the place, in its time;
    None where the sun doesn't both rise and set that day, or OpenWeatherMap
    doesn't say."""
    try:
        zone = timezone(timedelta(seconds=int(data["timezone"])))
        rise, sets = int(data["sys"]["sunrise"]), int(data["sys"]["sunset"])
    except KeyError, TypeError, ValueError, OverflowError:
        return None
    if not 0 < rise < sets:
        return None
    up, down = (datetime.fromtimestamp(at, zone) for at in (rise, sets))
    return _("🌅 {sunrise} · 🌇 {sunset} · {daylight} of daylight").format(
        sunrise=f"{up:%H:%M}",
        sunset=f"{down:%H:%M}",
        daylight=format_duration(down - up),
    )


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

    description = described(code, given)
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
    if sun := sun_line(data):
        lines.append(sun)
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


# What OpenWeatherMap said about each place, by where it is, and when
type Kept[T] = dict[tuple[str, str], tuple[float, T]]

# Each place's latest weather, and forecast
latest: Kept[dict[str, Any]] = {}
forecasts: Kept[list[Step]] = {}


async def fetch[T](
    url: str,
    kept: Kept[T],
    fresh: float,
    read: Callable[[Any], T],
    city: str = "",
    **params: str,
) -> tuple[Place, T]:
    """What OpenWeatherMap's url says about the city named, else about
    weather_city, as read() reads it, and where that is: what the bot got in
    the last fresh seconds, or else asked anew, which is counted for a city
    named. Raises WeatherError."""
    settings = get_settings()
    where = await place(city or settings.weather_city, counted=bool(city))
    now = monotonic()
    for old in [key for key, (at, _value) in kept.items() if now - at >= fresh]:
        del kept[old]
    key = (where.lat, where.lon)
    if key not in kept:
        data = await ask(
            url,
            counted=bool(city),
            lat=where.lat,
            lon=where.lon,
            units=settings.weather_units,
            lang=settings.language,
            **params,
        )
        kept[key] = (monotonic(), read(data))
    return where, kept[key][1]


async def fetch_weather(city: str = "") -> tuple[Place, dict[str, Any]]:
    """The weather in the city named, else in weather_city, and where that
    is, from the last 10 minutes. Raises WeatherError."""
    return await fetch(API_URL, latest, FRESH, lambda data: data, city)


def failed(what: str, city: str, error: Exception) -> str:
    """What to answer when the weather can't be had, logged. Styled."""
    if isinstance(error, TooOften):
        logger.info("%s: weather_calls_per_hour reached for places named", what)
        return escape(str(error))
    # A name that's no place is no failure, and what follows a command is for
    # DEBUG alone
    if not (city and isinstance(error, NoPlace)):
        log_failure(logger, what, error)
    return escape(error_text(error))


def named(where: Place, city: str) -> str:
    """How the heading names the place: as found, or weather_city as the
    config names it."""
    settings = get_settings()
    return where.name if city else settings.weather_city_name or settings.weather_city


async def weather_message(city: str = "") -> str:
    """The weather in the city named, else in weather_city; or why it can't
    be had. Styled."""
    settings = get_settings()
    try:
        where, data = await fetch_weather(city)
        return format_weather(
            data, named(where, city), datetime.now(settings.tz), settings.weather_units
        )
    except Exception as e:
        return failed("The weather", city, e)


class Weather(Handler):
    commands = (Command("/weather", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        city = argument(context.message.text)
        await answer(context, lambda: weather_message(city), slow=True, styled=True)


# The forecast


@dataclass(frozen=True)
class Step:
    """Three hours of a forecast."""

    at: datetime  # when they start, in the place's time
    temperature: float
    code: int
    description: str  # as OpenWeatherMap gives it
    rain: float  # the chance of rain or snow, 0 to 1


def forecast_steps(data: Any) -> list[Step]:
    """OpenWeatherMap's forecast, as steps. Raises WeatherError."""
    try:
        zone = timezone(timedelta(seconds=int(data["city"]["timezone"])))
        steps = [
            Step(
                at=datetime.fromtimestamp(int(item["dt"]), zone),
                temperature=float(item["main"]["temp"]),
                code=int(item["weather"][0]["id"]),
                description=str(item["weather"][0].get("description") or ""),
                rain=float(item.get("pop") or 0),
            )
            for item in data["list"]
        ]
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
    ) as e:
        raise WeatherError(_("the forecast data isn't as expected")) from e
    if not steps:
        raise WeatherError(_("the forecast data isn't as expected"))
    return steps


def severity(code: int) -> tuple[int, int]:
    """How bad the weather is, for a day's worst: a thunderstorm, snow, rain,
    drizzle, mist and the like, clouds, and a clear sky last; within each,
    by OpenWeatherMap's code, which has the heavier and cloudier later."""
    groups = {2: 6, 6: 5, 5: 4, 3: 3, 7: 2}
    return groups.get(code // 100, 1 if code > 800 else 0), code


def day_name(day: date, today: date) -> str:
    if day == today:
        return _("Today")
    if day == today + timedelta(days=1):
        return _("Tomorrow")
    return weekday_name(day)


def format_forecast(
    steps: list[Step], city: str, now: datetime, units: str = "metric"
) -> str:
    """Today and tomorrow, or tomorrow and the day after once today has no
    daytime left: each day's worst weather in the daytime, its lowest and
    highest temperature, and its highest chance of rain or snow. now is in
    the place's time. Styled."""
    days: dict[date, list[Step]] = {}
    for step in steps:
        days.setdefault(step.at.date(), []).append(step)
    today = now.date()
    shown = [
        (day, its)
        for day, its in days.items()
        if day > today
        or (day == today and any(step.at.hour in DAYTIME for step in its))
    ][:2]
    unit = UNITS.get(units, "°")
    lines: list[str] = []
    for day, its in shown:
        daytime = [step for step in its if step.at.hour in DAYTIME] or its
        worst = max(daytime, key=lambda step: severity(step.code))
        lines.append(
            f"{day_name(day, today)}: {condition_icon(worst.code)} "
            + described(worst.code, worst.description)
        )
        temperatures = [round(step.temperature) for step in its]
        line = _("🌡️ {low} to {high}").format(
            low=min(temperatures), high=f"{max(temperatures)}{unit}"
        )
        if (rain := round(max(step.rain for step in its), 1)) > 0:
            line += f" · ☔ {rain:.0%}"
        lines.append(line)
    heading = _("Forecast for {city}").format(city=city)
    return f"{bold(heading)}\n" + escape("\n".join(lines))


async def forecast_message(city: str = "") -> str:
    """The forecast for the city named, else for weather_city; or why it
    can't be had. Styled."""
    settings = get_settings()
    try:
        where, steps = await fetch(
            FORECAST_URL,
            forecasts,
            FORECAST_FRESH,
            forecast_steps,
            city,
            cnt=str(FORECAST_STEPS),
        )
        now = datetime.now(steps[0].at.tzinfo)
        return format_forecast(steps, named(where, city), now, settings.weather_units)
    except Exception as e:
        return failed("The forecast", city, e)


class Forecast(Handler):
    commands = (Command("/forecast", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        city = argument(context.message.text)
        await answer(context, lambda: forecast_message(city), slow=True, styled=True)
