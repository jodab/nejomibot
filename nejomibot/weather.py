"""Current weather from OpenWeatherMap, in weather_city. The bot asks
OpenWeatherMap's geocoding where the city is once, and then the weather
there, as OpenWeatherMap no longer develops its weather by city name."""

import logging
from datetime import datetime
from typing import Any

import aiohttp
from signalbot import DataMessageContext

from .client import client
from .commands import Command, Handler, answer
from .config import get_settings
from .i18n import N_, _, day_and_time
from .messages import ServiceError, error_text, log_failure, web_error

logger = logging.getLogger(__name__)

API_URL = "https://api.openweathermap.org/data/2.5/weather"
GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
TIMEOUT = aiohttp.ClientTimeout(total=15)

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
    lines = [
        _("Weather in {city}").format(city=city),
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
    return "\n".join(lines)


async def ask(url: str, **params: str) -> Any:
    """OpenWeatherMap's answer. Raises WeatherError."""
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


# Where the cities are, once found
places: dict[str, tuple[str, str]] = {}


async def place(city: str) -> tuple[str, str]:
    """The city's latitude and longitude, from OpenWeatherMap's geocoding,
    which takes the name as its weather by name did: Stockholm, or
    Stockholm,SE. Raises WeatherError."""
    if city not in places:
        found = await ask(GEOCODING_URL, q=city, limit="1")
        try:
            places[city] = (str(float(found[0]["lat"])), str(float(found[0]["lon"])))
        except (IndexError, KeyError, TypeError, ValueError) as e:
            raise WeatherError(
                _("OpenWeatherMap knows no place called {city}").format(city=city)
            ) from e
    return places[city]


async def fetch_weather() -> dict[str, Any]:
    settings = get_settings()
    lat, lon = await place(settings.weather_city)
    return await ask(
        API_URL,
        lat=lat,
        lon=lon,
        units=settings.weather_units,
        lang=settings.language,
    )


async def weather_message() -> str:
    settings = get_settings()
    try:
        data = await fetch_weather()
        return format_weather(
            data,
            settings.weather_city_name or settings.weather_city,
            datetime.now(settings.tz),
            settings.weather_units,
        )
    except Exception as e:
        log_failure(logger, "The weather", e)
        return error_text(e)


class Weather(Handler):
    commands = (Command("/weather"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, weather_message, slow=True)
