"""What the tests share besides fixtures: made-up people and groups, and a
stand-in for signal-cli-rest-api."""

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web
from PIL import Image, TiffImagePlugin
from signalbot import DataMessage, EditMessage, GroupInfo, TextStyle

ME = "+46700000000"
ALICE = "+46700000001"
BOB = "+46700000002"
GROUP = "group.ZmFtaWx5"
# Signal IDs, readable at a glance
ME_ID = "0e0e0e0e-0000-4000-8000-000000000000"
ALICE_ID = "a11ce000-0000-4000-8000-000000000001"
BOB_ID = "b0b00000-0000-4000-8000-000000000002"
CAROL_ID = "ca401000-0000-4000-8000-000000000003"
DAVE_ID = "da7e0000-0000-4000-8000-000000000004"
NOW_MS = int(time.time() * 1000)
DAY_MS = 24 * 60 * 60 * 1000
SAFETY_NUMBER = "".join(f"{i:05}" for i in range(12))


class Clock:
    """A stand-in for time.monotonic, which the test moves on."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# What an edit says of a message from before the bot's start
EDIT_FROM_BEFORE = (
    "✏️ That edit isn't run: the bot has started again since the message it "
    "edits, so it can't tell what that did. Send it as a new message instead."
)
# As a message in GROUP names it: by the ID signalbot calls internal
GROUP_INTERNAL_ID = "internal-Familjen"


def message_from(
    sender: str,
    text: str,
    *,
    in_group: bool = False,
    edit: bool = False,
    timestamp: int = NOW_MS,
) -> DataMessage:
    """A message as signalbot gives it: from the sender, by phone number or
    Signal ID, in a direct chat with the bot or in GROUP, sent at timestamp;
    with edit, an edit of the message sent then, as Signal names it."""
    by_number = sender.startswith("+")
    fields: dict[str, Any] = {
        "server_delivered_timestamp": 0,
        "server_received_timestamp": 0,
        "timestamp": timestamp + 1000 if edit else timestamp,
        "source": sender,
        "source_number": sender if by_number else None,
        "source_uuid": None if by_number else sender,
        "group_info": (
            GroupInfo.model_validate({"groupId": GROUP_INTERNAL_ID, "revision": 1})
            if in_group
            else None
        ),
        "text": text,
    }
    if edit:
        return EditMessage(**fields, target_sent_timestamp=timestamp)
    return DataMessage(**fields)


def make_jpeg(
    path: Path,
    taken: str | None = None,
    offset: str | None = None,
    created: str | None = None,
    where: tuple[float, float] | None = None,
) -> Path:
    """A small JPEG photo, with EXIF as a camera saves it: when it was
    taken, in a time zone, and where."""
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[0x9003] = taken  # DateTimeOriginal
    if offset:
        exif.get_ifd(0x8769)[0x9011] = offset  # OffsetTimeOriginal
    if created:
        exif.get_ifd(0x8769)[0x9004] = created  # CreateDate (DateTimeDigitized)
    if where:
        gps = exif.get_ifd(0x8825)
        for (ref, tag), value, sides in zip(
            ((1, 2), (3, 4)), where, ("NS", "EW"), strict=True
        ):
            gps[ref] = sides[value < 0]
            gps[tag] = dms(abs(value))
    Image.new("RGB", (4, 3), "red").save(path, exif=exif)
    return path


def dms(degrees: float) -> tuple[TiffImagePlugin.IFDRational, ...]:
    """Degrees, minutes and seconds, as cameras save them."""
    minutes, seconds = divmod(round(degrees * 3600 * 100), 60 * 100)
    whole, minutes = divmod(minutes, 60)
    return (
        TiffImagePlugin.IFDRational(whole, 1),
        TiffImagePlugin.IFDRational(minutes, 1),
        TiffImagePlugin.IFDRational(seconds, 100),
    )


def write(root: Path, path: str, text: str) -> None:
    """Write tmp file root/path, creating its folders."""
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text)


def text_styles(text: str, *styled: tuple[str, str]) -> list[TextStyle]:
    """Styles as Signal gives them with a message: each over the first time
    its words are in the text, counted in UTF-16 code units."""

    def length(part: str) -> int:
        return len(part.encode("utf-16-le")) // 2

    return [
        TextStyle(
            start=length(text[: text.index(words)]), length=length(words), style=style
        )
        for words, style in styled
    ]


def group_entry(group_id: str, name: str, **fields: Any) -> dict[str, Any]:
    """A group, as signal-cli-rest-api lists it."""
    return {
        "id": group_id,
        "internal_id": f"internal-{name}",
        "name": name,
        "description": "",
        "invite_link": "",
        "blocked": False,
        "member": True,
        "members": [],
        "admins": [],
        "pending_invites": [],
        "pending_requests": [],
        "permissions": {
            "add_members": "only-admins",
            "edit_group": "only-admins",
            "send_messages": "every-member",
        },
        **fields,
    }


# A fake signal-cli-rest-api's answers to GETs, shaped like its own, nulls
# included. "?all" is for all_recipients=true.
RESPONSES: dict[str, Any] = {
    "/v1/about": {
        "versions": ["v1", "v2"],
        "build": 2,
        "mode": "json-rpc",
        # As a build after 0.101 has it
        "version": "unset",
        "capabilities": {"v2/send": ["quotes", "mentions"]},
    },
    # As since its numberless support; before, [ME]
    "/v1/accounts": [{"number": ME, "aci": ME_ID}],
    f"/v1/contacts/{ME}": [
        {"number": ALICE, "uuid": ALICE_ID, "name": "Alice", "blocked": False},
    ],
    f"/v1/contacts/{ME}?all": [
        {
            "number": ME,
            "uuid": ME_ID,
            "name": "",
            "username": "mybot.01",
            "profile": {"given_name": "Mybot", "lastname": "", "about": "Hej"},
            "nickname": {"name": "", "given_name": "", "family_name": ""},
        },
        {"number": ALICE, "uuid": ALICE_ID, "name": "Alice", "blocked": False},
        {
            "number": BOB,
            "uuid": BOB_ID,
            "name": "",
            "profile_name": "",
            "profile": {"given_name": "Bob", "lastname": "Berg", "about": "Hi*"},
            "nickname": {"name": "", "given_name": "", "family_name": ""},
            "blocked": True,
        },
        {"number": "", "uuid": CAROL_ID, "name": None, "profile": None},
    ],
    f"/v1/identities/{ME}": [
        {
            "number": ALICE,
            "uuid": ALICE_ID,
            "status": "TRUSTED_VERIFIED",
            "added": "1",
            "safety_number": SAFETY_NUMBER,
        },
        {
            "number": BOB,
            "uuid": BOB_ID,
            "status": "UNTRUSTED",
            "added": str(NOW_MS - DAY_MS),
        },
        {"number": "", "uuid": CAROL_ID, "status": "TRUSTED_UNVERIFIED", "added": "0"},
    ],
    f"/v1/devices/{ME}": [
        {"id": 2, "name": "signal-cli", "last_seen_timestamp": NOW_MS},
        {"id": 1, "name": None, "last_seen_timestamp": NOW_MS - 3 * DAY_MS},
    ],
    f"/v1/groups/{ME}": [
        group_entry(
            GROUP,
            "Familjen",
            members=[ME, ALICE, CAROL_ID],
            admins=[ME_ID],
            pending_invites=[BOB],
            pending_requests=[DAVE_ID],
        ),
        group_entry("group.b2xk", "Old", member=False),
    ],
}


@dataclass(frozen=True)
class Request:
    method: str
    path: str  # decoded: + for %2B
    query: dict[str, str]
    body: Any  # its JSON, if it had any


type Route = Callable[[web.Request], Awaitable[web.StreamResponse]]


class FakeApi:
    """A stand-in for signal-cli-rest-api. It answers GETs from its responses,
    a copy of RESPONSES, and the rest as signal-cli-rest-api does when all
    goes well. A test can answer a route its own way with route(). Records
    every request."""

    def __init__(self) -> None:
        self.responses: dict[str, Any] = copy.deepcopy(RESPONSES)
        self.routes: dict[tuple[str, str], Route] = {}
        self.requests: list[Request] = []
        self.arrived = asyncio.Condition()  # notified of every request
        self.timestamp = NOW_MS

    def route(self, method: str, path: str, handler: Route) -> None:
        self.routes[method, path] = handler

    def bodies(self, method: str, path: str) -> list[Any]:
        """What was sent to the route, oldest first."""
        return [r.body for r in self.requests if (r.method, r.path) == (method, path)]

    async def wait_for(self, method: str, path: str, count: int) -> None:
        """Until the route has had that many requests."""
        async with self.arrived:
            await self.arrived.wait_for(lambda: len(self.bodies(method, path)) >= count)

    def next_timestamp(self) -> str:
        self.timestamp += 1
        return str(self.timestamp)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.json() if request.can_read_body else None
        path = request.path
        self.requests.append(Request(request.method, path, dict(request.query), body))
        async with self.arrived:
            self.arrived.notify_all()
        if route := self.routes.get((request.method, path)):
            return await route(request)
        return self.answer(request.method, path, request.query)

    def answer(self, method: str, path: str, query: Any) -> web.Response:
        if method == "GET":
            key = path + ("?all" if "all_recipients" in query else "")
            if key not in self.responses:
                return web.json_response({"error": "Not found"}, status=404)
            return web.json_response(self.responses[key])
        if path == "/v2/send":
            return web.json_response([{"timestamp": self.next_timestamp()}], status=201)
        if path.startswith("/v1/remote-delete/"):
            return web.json_response({"timestamp": self.next_timestamp()})
        return web.Response(status=204)
