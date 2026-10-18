from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from nejomibot import info
from nejomibot.config import get_settings
from nejomibot.messages import error_text

RATES = {"EUR": 1, "SEK": 11.19, "USD": 1.16}

CLOCKS = '{"🇸🇪 Stockholm": "Europe/Stockholm", "🇫🇮 Helsingfors": "Europe/Helsinki"}'


@pytest.fixture
def clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_CLOCKS", CLOCKS)
    get_settings.cache_clear()


@pytest.mark.usefixtures("clocks", "swedish")
def test_format_times_summer() -> None:
    now = datetime(2026, 10, 11, 13, 30, tzinfo=UTC)
    assert info.format_times(now) == (
        "**Tidszoner**\n"
        "🇸🇪 Stockholm: 15:30 (Sommartid)\n"
        "🇫🇮 Helsingfors: 16:30 (Sommartid)\n"
        "⏰ Tidsskillnad: 1 tim"
    )


@pytest.mark.usefixtures("clocks", "swedish")
def test_format_times_winter() -> None:
    now = datetime(2027, 1, 4, 7, 5, tzinfo=UTC)
    assert info.format_times(now).splitlines()[1:3] == [
        "🇸🇪 Stockholm: 08:05 (Vintertid)",
        "🇫🇮 Helsingfors: 09:05 (Vintertid)",
    ]


@pytest.mark.usefixtures("clocks")
def test_format_times_in_english() -> None:
    now = datetime(2027, 1, 4, 7, 5, tzinfo=UTC)
    assert info.format_times(now) == (
        "**Time zones**\n"
        "🇸🇪 Stockholm: 08:05 (Standard time)\n"
        "🇫🇮 Helsingfors: 09:05 (Standard time)\n"
        "⏰ Time difference: 1 h"
    )


def test_format_times_without_clocks_shows_the_bots_time() -> None:
    now = datetime(2026, 10, 11, 13, 30, tzinfo=UTC)
    assert info.format_times(now) == "**Time zones**\nStockholm: 15:30 (Summer time)"


def test_format_times_escapes_the_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_CLOCKS", '{"*Home*": "UTC"}')
    get_settings.cache_clear()
    now = datetime(2026, 10, 11, 13, 30, tzinfo=UTC)
    assert info.format_times(now).splitlines()[1] == "\\*Home\\*: 13:30 (Standard time)"


@pytest.mark.usefixtures("swedish")
def test_format_rates() -> None:
    assert info.format_rates("EUR", "SEK", 11.19) == (
        "**Valutakurser**\n💶 1 EUR = 11.19 SEK\n💷 1 SEK = 0.089 EUR"
    )


async def test_info_message_without_an_exchange_rate() -> None:
    assert "**Exchange rates**" not in await info.info_message()


@pytest.mark.usefixtures("swedish")
async def test_info_message_when_rates_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_EXCHANGE_RATE", '["EUR", "SEK"]')
    get_settings.cache_clear()
    monkeypatch.setattr(info, "RATES_URL", "http://127.0.0.1:1/latest/{}")
    message = await info.info_message()
    assert message.startswith("**Tidszoner**\n")
    assert "\n\n**Valutakurser**\nNågot gick fel: " in message


@pytest.fixture
async def rates_api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    """A stand-in for the exchange rate API: set 'status' and 'body'."""
    reply: dict[str, Any] = {"status": 200, "body": {}}

    async def latest(request: web.Request) -> web.Response:
        reply["base"] = request.match_info["base"]
        return web.json_response(reply["body"], status=reply["status"])

    app = web.Application()
    app.router.add_get("/v6/latest/{base}", latest)
    async with TestServer(app, host="127.0.0.1") as server:
        url = f"{server.make_url('/v6/latest/')}{{}}"
        monkeypatch.setattr(info, "RATES_URL", url)
        yield reply


async def test_fetch_rate(rates_api: dict[str, Any]) -> None:
    rates_api["body"] = {"result": "success", "base_code": "EUR", "rates": RATES}
    assert await info.fetch_rate("EUR", "SEK") == 11.19
    assert rates_api["base"] == "EUR"


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (
            200,
            {"result": "error", "error-type": "unsupported-code"},
            "the exchange rate API answered with an error (unsupported-code)",
        ),
        (
            200,
            {"result": "success", "rates": {"EUR": 1}},
            "the exchange rate API has no rate for SEK",
        ),
        (200, ["odd"], "the exchange rates can't be read"),
        (503, {}, "503 Service Unavailable"),
    ],
)
async def test_fetch_rate_fails(
    rates_api: dict[str, Any], status: int, body: Any, error: str
) -> None:
    rates_api["status"], rates_api["body"] = status, body
    with pytest.raises(Exception) as failed:
        await info.fetch_rate("EUR", "SEK")
    assert error_text(failed.value) == f"Something went wrong: {error}"
