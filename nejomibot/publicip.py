"""Our public IPv4 and IPv6 addresses, and the network that announces them.

The addresses come from Cloudflare's trace page, asked over IPv4 and over IPv6.
The network (ASN, holder, announced prefix) and location come from RIPEstat,
the RIPE NCC's free API, and the name from reverse DNS. Everything is best
effort: whatever can't be found is left out.
"""

import asyncio
import ipaddress
import logging
import socket
from typing import Any

import aiohttp

from .client import client
from .i18n import _

logger = logging.getLogger(__name__)

# www.: some DNS blocklists hide one.one.one.one, which also serves the page
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
RIPESTAT_URL = "https://stat.ripe.net/data/{}/data.json"
TIMEOUT = aiohttp.ClientTimeout(total=5)
FAMILIES = {"IPv4": socket.AF_INET, "IPv6": socket.AF_INET6}


def describe_error(e: Exception) -> str:
    """Why a connection failed, e.g. 'Network is unreachable'."""
    if isinstance(e, aiohttp.ClientConnectorError) and e.strerror:
        return e.strerror
    return str(e) or type(e).__name__


async def public_ip(family: socket.AddressFamily) -> str:
    """Our address as the internet sees it, connecting over this family only,
    so in a session of its own."""
    connector = aiohttp.TCPConnector(family=family)
    async with (
        aiohttp.ClientSession(timeout=TIMEOUT, connector=connector) as session,
        session.get(TRACE_URL) as response,
    ):
        response.raise_for_status()
        text = await response.text()
    lines = (line.partition("=") for line in text.splitlines())
    fields = {name: value for name, _equals, value in lines}
    return str(ipaddress.ip_address(fields.get("ip", "")))


async def ripestat(call: str, ip: str) -> Any:
    params = {"resource": ip, "sourceapp": "nejomibot"}
    async with client.session().get(
        RIPESTAT_URL.format(call), params=params, timeout=TIMEOUT
    ) as response:
        response.raise_for_status()
        return (await response.json())["data"]


def format_network(overview: Any) -> list[str]:
    """E.g. ['AS64500 EXAMPLE-AS Example Telecom', '203.0.113.0/24'], from
    prefix-overview: who announces the address, a line each, then the prefix."""
    if not overview["announced"]:
        return [_("not announced")]
    holders = [f"AS{asn['asn']} {asn['holder']}" for asn in overview["asns"]]
    return [*holders, overview["resource"]]


def format_location(geo: Any) -> str | None:
    """E.g. 'Stockholm, SE': the place covering most of the address
    (maxmind-geo-lite)."""
    places = [
        place
        for resource in geo["located_resources"]
        for place in resource["locations"]
    ]
    if not places:
        return None
    place = max(places, key=lambda place: place["covered_percentage"])
    return (
        ", ".join(
            part for part in (place["city"], place["country"]) if part and part != "?"
        )
        or None
    )


async def network(ip: str) -> list[str]:
    try:
        return format_network(await ripestat("prefix-overview", ip))
    except Exception as e:
        logger.warning("No network for %s: %r", ip, e)
        return []


async def location(ip: str) -> str | None:
    try:
        return format_location(await ripestat("maxmind-geo-lite", ip))
    except Exception as e:
        logger.warning("No location for %s: %r", ip, e)
        return None


async def reverse_dns(ip: str) -> str | None:
    try:
        async with asyncio.timeout(3):
            host, _port = await asyncio.get_running_loop().getnameinfo(
                (ip, 0), socket.NI_NAMEREQD
            )
    except OSError, TimeoutError:
        return None
    return host


async def address_lines(name: str, family: socket.AddressFamily) -> list[str]:
    """E.g. ['IPv4 203.0.113.7', 'host.example.net', 'AS64500 EXAMPLE-AS …',
    '203.0.113.0/24 · Stockholm, SE']: short lines, for Signal's bubbles."""
    try:
        ip = await public_ip(family)
    except Exception as e:
        logger.info("No public %s address: %r", name, e)
        return [
            _("{family} none ({error})").format(family=name, error=describe_error(e))
        ]
    host, where, place = await asyncio.gather(
        reverse_dns(ip), network(ip), location(ip)
    )
    lines = [f"{name} {ip}", *([host] if host else []), *where]
    if place:
        # On the prefix's line, or a line of its own
        if where:
            lines[-1] += f" · {place}"
        else:
            lines.append(place)
    return lines


async def internet_lines() -> list[str]:
    """Our public address in each family, with its network and location."""
    per_family = await asyncio.gather(
        *(address_lines(name, family) for name, family in FAMILIES.items())
    )
    return [line for lines in per_family for line in lines]
