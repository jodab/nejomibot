import asyncio

import aiohttp

from nejomibot.client import client


def test_a_session_belongs_to_its_event_loop() -> None:
    # The bot waits for the account on a loop of its own, then signalbot runs
    # another: a session made on the first can't be used on the second
    async def session() -> aiohttp.ClientSession:
        return client.session()

    first_loop, second_loop = asyncio.new_event_loop(), asyncio.new_event_loop()
    try:
        first = first_loop.run_until_complete(session())
        second = second_loop.run_until_complete(session())
        assert second is not first
        assert second_loop.run_until_complete(session()) is second
        second_loop.run_until_complete(client.close())
        first_loop.run_until_complete(first.close())
    finally:
        first_loop.close()
        second_loop.close()
