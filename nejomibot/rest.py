"""Requests straight to signal-cli-rest-api, for what signalbot can't do.

The bot talks to Signal through signalbot: sending, receiving, receipts,
typing, deleting, groups and naming contacts. signalbot has nothing for the
rest, so these functions ask signal-cli-rest-api themselves, each saying what
signalbot lacks. Once signalbot has it, the function can go.
"""

import base64
import contextlib
import json
from collections.abc import AsyncGenerator, Collection, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, ValidationError

from .client import client
from .config import get_settings

TIMEOUT = aiohttp.ClientTimeout(total=30)
# A profile change waits for Signal's servers, and an avatar for its upload too
SLOW_TIMEOUT = aiohttp.ClientTimeout(total=60)


class RestError(Exception):
    """signal-cli-rest-api answered with an error; the message is its own."""

    def __init__(self, status: int, text: str) -> None:
        super().__init__(text)
        self.status = status


class ErrorResponse(BaseModel):
    error: str


def error_of(body: str) -> str:
    """The error in signal-cli-rest-api's answer, or the answer itself."""
    try:
        return ErrorResponse.model_validate_json(body).error
    except ValidationError:
        return body.strip()


def account_path(prefix: str, *more: str) -> str:
    """The account's part of the API, e.g. /v1/devices/%2B46700000000."""
    parts = [get_settings().account, *more]
    return prefix + "".join(f"/{quote(part, safe='')}" for part in parts)


async def request(
    method: str,
    path: str,
    *,
    payload: Any = None,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    slow: bool = False,
) -> bytes:
    """One request, sending the payload as JSON; the answer's body. A slow one
    waits for Signal's servers. Raises RestError if signal-cli-rest-api
    answers with an error, aiohttp.ClientError or TimeoutError if it can't be
    reached in time."""
    url = f"http://{get_settings().signal_service}{path}"
    timeout = SLOW_TIMEOUT if slow else TIMEOUT
    async with client.session().request(
        method, url, json=payload, params=params, timeout=timeout
    ) as response:
        body = await response.read()
        if not response.ok:
            raise RestError(response.status, error_of(body.decode(errors="replace")))
        return body


async def get_json(path: str, **params: str) -> Any:
    return json.loads(await request("GET", path, params=params))


async def get_file(path: str) -> bytes | None:
    """A file, or None if there's none."""
    try:
        return await request("GET", path)
    except RestError as e:
        if e.status == 404:
            return None
        raise


# The account


async def accounts() -> Any:
    """The accounts registered in signal-cli. signalbot assumes its account is
    there, and has no way to ask."""
    return await get_json("/v1/accounts")


async def devices() -> Any:
    """The account's linked devices. Not in signalbot. signal-cli asks Signal's
    servers for them, so an answer also shows that Signal can be reached and
    knows the account."""
    return await get_json(account_path("/v1/devices"))


async def recipients(*, everyone: bool) -> Any:
    """The contacts, or with everyone, every recipient signal-cli knows, with
    their names, profiles and whether they're blocked. signalbot can only
    name a contact, not list them."""
    params = {"all_recipients": "true"} if everyone else {}
    return await get_json(account_path("/v1/contacts"), **params)


async def recipient(uuid: str) -> Any:
    """One recipient, by Signal ID. Asking makes signal-cli fetch their profile
    now, instead of after its six-hour cache. Not in signalbot."""
    return await get_json(account_path("/v1/contacts", uuid), all_recipients="true")


async def identities() -> Any:
    """Everyone's safety numbers. Not in signalbot."""
    return await get_json(account_path("/v1/identities"))


async def name_contact(recipient: str, name: str) -> None:
    """Make someone a contact by this name: here, someone by Signal
    username, as u:alice.42, whom signal-cli finds by it on Signal's servers,
    and keeps it with. signalbot's contacts.update takes a bare username,
    which signal-cli reads as a phone number."""
    payload = {"recipient": recipient, "name": name}
    await request("PUT", account_path("/v1/contacts"), payload=payload, slow=True)


async def look_up(numbers: Collection[str]) -> Any:
    """Whether each phone number is on Signal, from Signal's contact
    discovery, which waits for Signal's servers. signal-cli keeps each number
    found with its owner's Signal ID, so it knows who that is from then on;
    the answer has just the number and whether it was found. Signal limits
    how many numbers an account looks up. Not in signalbot."""
    params = [("numbers", number) for number in numbers]
    path = account_path("/v1/search")
    return json.loads(await request("GET", path, params=params, slow=True))


async def trust(recipient: str, safety_number: str) -> None:
    """Mark the recipient's safety number as verified; signal-cli refuses if
    it isn't theirs. Not in signalbot."""
    path = account_path("/v1/identities", "trust", recipient)
    await request("PUT", path, payload={"verified_safety_number": safety_number})


# The bot's own profile and username: signalbot can't change them


async def avatar(uuid: str) -> bytes | None:
    """A recipient's profile picture, such as the bot's own; None if they have
    none."""
    return await get_file(account_path("/v1/contacts", uuid, "avatar"))


async def update_profile(
    given_name: str, *, about: str | None, avatar: bytes | None
) -> None:
    """Set the profile's given name, and About unless it's None. The avatar
    goes unless it's sent along; the family name and About's emoji stay."""
    payload = {"name": given_name}
    if about is not None:
        payload["about"] = about
    if avatar is not None:
        payload["base64_avatar"] = base64.b64encode(avatar).decode()
    path = account_path("/v1/profiles")
    await request("PUT", path, payload=payload, slow=True)


async def set_username(username: str) -> Any:
    """Set the username; Signal adds a number to it unless it has one. The
    answer has it in full, and a link that starts a chat with the bot."""
    path = account_path("/v1/accounts", "username")
    payload = {"username": username}
    return json.loads(await request("POST", path, payload=payload, slow=True))


async def delete_username() -> None:
    path = account_path("/v1/accounts", "username")
    await request("DELETE", path, slow=True)


async def attachment(attachment_id: str) -> bytes | None:
    """What was attached to a message, if signal-cli kept it. signalbot only
    fetches attachments if it fetches every one sent to the bot, in every
    chat."""
    return await get_file(f"/v1/attachments/{quote(attachment_id, safe='')}")


@contextlib.asynccontextmanager
async def received() -> AsyncGenerator[aiohttp.ClientWebSocketResponse]:
    """A websocket of the bot's own, beside signalbot's, with everything
    signal-cli-rest-api receives, each as its JSON: in json-rpc mode it sends
    every message to every websocket. For the receipts for the bot's
    messages, which signalbot drops: its parser knows none, as of 2.1.3.
    Raises aiohttp.ClientError if it can't be opened."""
    url = f"ws://{get_settings().signal_service}{account_path('/v1/receive')}"
    async with client.session().ws_connect(url) as websocket:
        yield websocket
