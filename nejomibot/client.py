"""The bot's HTTP client, for what it asks itself: signal-cli-rest-api, for
what signalbot can't do (rest.py), OpenWeatherMap, the exchange rates,
RIPEstat and the health check service. One session for all of them, as
aiohttp advises, so connections are reused; signalbot has its own.
"""

import asyncio

import aiohttp


class Client:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def session(self) -> aiohttp.ClientSession:
        """The session, made on first use. A session belongs to the event loop
        it's made on, so on another loop it's made anew; the old one should
        have been closed on its own loop, as close() does."""
        loop = asyncio.get_running_loop()
        if self._session is None or self._session.closed or self._loop is not loop:
            self._session, self._loop = aiohttp.ClientSession(), loop
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = self._loop = None


client = Client()
