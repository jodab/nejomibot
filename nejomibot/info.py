"""The time in the places set in clocks, and the exchange rate set in
exchange_rate. The rates change once a day, when the API says it has new
ones: until then, the bot takes those it has."""

import logging
import time
from datetime import UTC, datetime, timedelta

import aiohttp
from pydantic import BaseModel, Field, ValidationError
from signalbot import DataMessageContext

from .client import client
from .commands import Command, Handler, answer
from .config import get_settings
from .i18n import _
from .messages import ServiceError, error_text, escape, log_failure

logger = logging.getLogger(__name__)

# ExchangeRate-API's open access endpoint, updated daily
RATES_URL = "https://open.er-api.com/v6/latest/{}"
TIMEOUT = aiohttp.ClientTimeout(total=5)
# Rates are kept till the API's next update, this long at least, should
# that be due already, and a day at most
KEPT_AT_LEAST = 10 * 60  # seconds
KEPT_AT_MOST = 24 * 60 * 60


def season(local: datetime) -> str:
    dst = local.dst()
    return _("Summer time") if dst and dst.total_seconds() > 0 else _("Standard time")


def format_times(now: datetime) -> str:
    """Each clock's time; with two, how far apart they are."""
    local = {
        name: now.astimezone(zone) for name, zone in get_settings().clock_zones.items()
    }
    lines = [f"**{_('Time zones')}**"]
    lines += [
        escape(f"{name}: {at:%H:%M} ({season(at)})") for name, at in local.items()
    ]
    if len(local) == 2:
        first, second = local.values()
        difference = (second.utcoffset() or timedelta()) - (
            first.utcoffset() or timedelta()
        )
        lines.append(
            escape(
                _("⏰ Time difference: {hours} h").format(
                    hours=f"{difference.total_seconds() / 3600:g}"
                )
            )
        )
    return "\n".join(lines)


def format_rates(base: str, quote: str, rate: float) -> str:
    return (
        f"**{_('Exchange rates')}**\n"
        f"💶 1 {base} = {rate:.2f} {quote}\n"
        f"💷 1 {quote} = {1 / rate:.3f} {base}"
    )


class RatesError(ServiceError):
    """The exchange rates can't be had."""


class Rates(BaseModel):
    """The exchange rate API's answer."""

    result: str  # success or error
    error_type: str | None = Field(default=None, alias="error-type")
    rates: dict[str, float] = {}
    # When it has the next rates, in seconds since the epoch
    next_update: float | None = Field(default=None, alias="time_next_update_unix")


# The rates by the currency they're for, and until when, by time.time()
kept: dict[str, tuple[float, dict[str, float]]] = {}


async def fetch_rates(base: str) -> Rates:
    """What the API says of base. Raises RatesError, or aiohttp's error."""
    async with client.session().get(
        RATES_URL.format(base), timeout=TIMEOUT
    ) as response:
        response.raise_for_status()
        body = await response.read()
    try:
        answer = Rates.model_validate_json(body)
    except ValidationError as e:
        raise RatesError(_("the exchange rates can't be read")) from e
    if answer.result != "success":
        raise RatesError(
            _("the exchange rate API answered with an error ({error})").format(
                error=answer.error_type
            )
        )
    return answer


async def fetch_rate(base: str, quote: str, *, fresh: bool = False) -> float:
    """What one base costs in quote, as the API said last, until it has
    newer rates; fresh, as it says now. Raises RatesError, or aiohttp's
    error."""
    now = time.time()
    if fresh or (found := kept.get(base)) is None or now >= found[0]:
        answer = await fetch_rates(base)
        until = min(
            max(answer.next_update or 0, now + KEPT_AT_LEAST), now + KEPT_AT_MOST
        )
        found = kept[base] = (until, answer.rates)
    if quote not in found[1]:
        raise RatesError(
            _("the exchange rate API has no rate for {currency}").format(currency=quote)
        )
    return found[1][quote]


async def info_message() -> str:
    """The times always; the exchange rate, if set, or why it is missing."""
    times = format_times(datetime.now(UTC))
    if (pair := get_settings().exchange_rate) is None:
        return times
    try:
        rates = format_rates(*pair, await fetch_rate(*pair))
    except Exception as e:
        log_failure(logger, "The exchange rate", e)
        rates = f"**{_('Exchange rates')}**\n{escape(error_text(e))}"
    return f"{times}\n\n{rates}"


class Info(Handler):
    everyday = True
    commands = (Command("/info"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, info_message, slow=True, styled=True)
