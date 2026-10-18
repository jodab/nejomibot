import socket
from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiohttp import web

from nejomibot import publicip

OVERVIEW = {
    "announced": True,
    "resource": "203.0.113.0/24",
    "asns": [{"asn": 64500, "holder": "EXAMPLE-AS Example Telecom"}],
}
GEO = {
    "located_resources": [
        {
            "locations": [
                {"country": "SE", "city": "Stockholm", "covered_percentage": 10.0},
                {"country": "SE", "city": "Stockholm", "covered_percentage": 90.0},
            ]
        }
    ]
}


def test_format_network() -> None:
    assert publicip.format_network(OVERVIEW) == [
        "AS64500 EXAMPLE-AS Example Telecom",
        "203.0.113.0/24",
    ]
    assert publicip.format_network({**OVERVIEW, "asns": []}) == ["203.0.113.0/24"]
    assert publicip.format_network({**OVERVIEW, "announced": False}) == [
        "not announced"
    ]


def test_format_location_picks_the_largest_place() -> None:
    assert publicip.format_location(GEO) == "Stockholm, SE"


def test_format_location_unknown() -> None:
    unknown = {"country": "?", "city": "", "covered_percentage": 100.0}
    assert publicip.format_location({"located_resources": []}) is None
    assert (
        publicip.format_location({"located_resources": [{"locations": [unknown]}]})
        is None
    )


@pytest.fixture
async def services(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    """Local stand-ins for Cloudflare's trace page and RIPEstat."""
    replies: dict[str, Any] = {
        "trace": "fl=1f1\nh=www.cloudflare.com\nip=203.0.113.7\nloc=SE\n",
        "prefix-overview": OVERVIEW,
        "maxmind-geo-lite": GEO,
    }

    async def trace(request: web.Request) -> web.Response:
        return web.Response(text=replies["trace"])

    async def ripestat(request: web.Request) -> web.Response:
        replies["query"] = dict(request.query)
        return web.json_response({"data": replies[request.match_info["call"]]})

    async def reverse_dns(ip: str) -> str | None:
        return "home.example.net"

    app = web.Application()
    app.router.add_get("/cdn-cgi/trace", trace)
    app.router.add_get("/data/{call}/data.json", ripestat)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    base = f"http://127.0.0.1:{runner.addresses[0][1]}"
    monkeypatch.setattr(publicip, "TRACE_URL", f"{base}/cdn-cgi/trace")
    monkeypatch.setattr(publicip, "RIPESTAT_URL", f"{base}/data/{{}}/data.json")
    monkeypatch.setattr(publicip, "reverse_dns", reverse_dns)
    yield replies
    await runner.cleanup()


async def test_public_ip(services: dict[str, Any]) -> None:
    assert await publicip.public_ip(socket.AF_INET) == "203.0.113.7"


async def test_public_ip_rejects_garbage(services: dict[str, Any]) -> None:
    services["trace"] = "<html>blocked</html>"
    with pytest.raises(ValueError, match="does not appear to be"):
        await publicip.public_ip(socket.AF_INET)


async def test_address_lines(services: dict[str, Any]) -> None:
    # Short lines, as Signal's bubbles are narrow
    assert await publicip.address_lines("IPv4", socket.AF_INET) == [
        "IPv4 203.0.113.7",
        "home.example.net",
        "AS64500 EXAMPLE-AS Example Telecom",
        "203.0.113.0/24 · Stockholm, SE",
    ]
    assert services["query"] == {"resource": "203.0.113.7", "sourceapp": "nejomibot"}


async def test_address_lines_without_ripestat(
    services: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(publicip, "RIPESTAT_URL", "http://127.0.0.1:1/{}")
    assert await publicip.address_lines("IPv4", socket.AF_INET) == [
        "IPv4 203.0.113.7",
        "home.example.net",
    ]


async def test_internet_lines_without_ipv6(services: dict[str, Any]) -> None:
    # The stand-in only listens on IPv4, like a container without IPv6
    lines = await publicip.internet_lines()
    assert lines[0] == "IPv4 203.0.113.7"
    assert lines[-1].startswith("IPv6 none (")


async def test_address_lines_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publicip, "TRACE_URL", "http://127.0.0.1:1/cdn-cgi/trace")
    assert await publicip.address_lines("IPv4", socket.AF_INET) == [
        "IPv4 none (Connect call failed ('127.0.0.1', 1))"
    ]
