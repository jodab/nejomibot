"""nejomibot-chat's side in the bot (chat_cli.py): the admins' messages from a
terminal, and the messages the bot has received, in every chat.

A message from nejomibot-chat is taken as from the first admin in a direct
chat with the bot, and goes through the bot's handlers as one from Signal
does, with the files attached to it as if signalbot had downloaded them
(Attachment.base64_content), which /msg posts and /avatar takes, and the
formatting its marks give it as if Signal's formatting menu had
(styles.typed()), which /msg and specials keep. Its answers
go back to the terminal, rather than to Signal; everything else is as in the
direct chat: what posts elsewhere, as /msg, /run and /remind, posts there,
and the lists that number things, as /incoming, number them for the admin.
No read receipt or typing goes to Signal, as no message came from there.
A message for some of /chats' chats, from a chat with them in the terminal,
runs its command there, as /run does, if it starts with one, and posts
there, as /msg does, if it doesn't.

The bot keeps the 100 latest messages it receives, in every chat, the
admins' and the groups' too, in memory only, as /incoming keeps its own: an
edit replaces the message it edits, and one deleted for everyone, or that
disappears, goes. nejomibot-chat lists them (--recent), and hears of each
new one while it follows them (--follow), of every chat or of some of
/chats' alone, which a chat with them shows. With received_attachments, each
also keeps where signal-cli keeps its attachments, not the files, which
--save fetches, up to 25 MB each.

The bot listens once signalbot is ready, on a Unix socket in Linux's
abstract namespace, as for the container's health check. Any process in the
bot's network namespace may connect to such a socket, as
signal-cli-rest-api's container does in the Quadlet, which shares it, so the
bot answers only its own user and root, by the socket's peer credentials.
"""

import asyncio
import base64
import contextlib
import functools
import json
import logging
import os
import re
import socket
import struct
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from signalbot import Attachment, DataMessage, SendMessage, SignalBot, TextMode

from . import access, chat_cli, rest
from .commands import canonical, known
from .config import get_settings
from .incoming import File, Inbox, Received
from .messages import EXPECTED, describe, for_chat, to_terminal
from .styles import MENTION, STYLES, escape, styles_of, typed, unmarked
from .timers import Chat, chats_numbered, made_up, timekeeper

logger = logging.getLogger(__name__)

# The longest first line of a request: a long message's text
HEADER_LIMIT = 1024 * 1024  # bytes
# How long the bot reads what nejomibot-chat still sends after a refusal
DRAIN_FOR = 60  # seconds
# How many received messages a follower may fall behind by; the rest are
# left out
BEHIND = 100
CREDENTIALS = struct.Struct("3i")  # SO_PEERCRED's: pid, uid, gid
# What an attachment's type and name may be, as signal-cli-rest-api reads
# them in a data URL
CONTENT_TYPE = re.compile(r"^[\w.+-]+/[\w.+-]+$")
NOT_IN_NAMES = re.compile(r"[;,/\\\x00-\x1f]")
DATA_URL = re.compile(r"^data:([^;,]*)(?:;filename=([^;,]*))?;base64,")


class Refused(Exception):
    """What the bot says no to, in words for nejomibot-chat."""


class Attached(BaseModel):
    """A file nejomibot-chat attaches, as its request names it: its bytes
    follow the request."""

    model_config = ConfigDict(extra="forbid")

    filename: str = ""
    content_type: str = chat_cli.UNKNOWN
    size: Annotated[int, Field(ge=0)]


class Request(BaseModel):
    """What nejomibot-chat asks, on the first line it sends: the bot's answers
    to a message, with the files attached to it; or the messages the bot
    received, the latest of them, those to come, or both. With chats, numbers
    from /chats, the message is for those chats, and only theirs come."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    attachments: list[Attached] = []
    recent: Annotated[int, Field(ge=1)] | None = None
    follow: bool = False
    files: bool = False  # the received messages' files too, where kept
    chats: list[Annotated[int, Field(ge=1)]] = []


class Recent(Inbox):
    """The latest messages the bot received, in every chat, from everyone;
    and those who follow them, a queue each."""

    def __init__(self) -> None:
        super().__init__(kept=chat_cli.RECENT)
        self.followers: set[asyncio.Queue[Received]] = set()

    def wanted(self, message: DataMessage) -> bool:
        return True

    def files_of(self, message: DataMessage) -> tuple[File, ...]:
        """Where signal-cli keeps the message's attachments, if they're
        wanted: if it doesn't, there's none to fetch."""
        if not get_settings().received_attachments:
            return ()
        return tuple(
            File(
                each.local_filename,
                each.content_type or chat_cli.UNKNOWN,
                each.remote_filename or "",
                each.size,
            )
            for each in message.attachments or []
            if each.local_filename
        )

    def keep(self, message: DataMessage, chat: str = "") -> Received | None:
        if (received := super().keep(message, chat)) is not None:
            for queue in self.followers:
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(received)
        return received


recent = Recent()


def shown(text: str, names: access.Names, *, styled: bool) -> dict[str, Any]:
    """A text as nejomibot-chat shows it: each mention as @ and a name, and
    in a styled text, the marks taken out, and their styles beside it, each
    by where it starts and how long it is, in characters."""

    def named(found: re.Match[str]) -> str:
        name = f"@{names.of(found[1])}"
        return escape(name) if styled else name

    text = MENTION.sub(named, text)
    if not styled:
        return {"text": text, "styles": []}
    plain, ranges = unmarked(text)
    each = [*styles_of(plain, ranges), frozenset[str]()]
    styles: list[dict[str, Any]] = []
    for style in sorted(STYLES):
        start: int | None = None
        for i, here in enumerate(each):
            if style in here and start is None:
                start = i
            elif style not in here and start is not None:
                styles.append({"start": start, "length": i - start, "style": style})
                start = None
    return {"text": plain, "styles": styles}


def sent_file(data: str) -> dict[str, Any]:
    """A file the bot sends, as base64, or in a data URL, with a type and a
    name."""
    content_type, filename = "", ""
    if found := DATA_URL.match(data):
        content_type, filename, data = found[1], found[2] or "", data[found.end() :]
    else:
        content_type = chat_cli.content_type(base64.b64decode(data[:24]))
    size = len(data) * 3 // 4 - data[-2:].count("=")
    return {
        "content_type": content_type,
        "filename": filename,
        "size": size,
        "base64": data,
    }


def answer_of(message: SendMessage, names: access.Names) -> dict[str, Any]:
    styled = message.text_mode == TextMode.STYLED
    files = [sent_file(data) for data in message.base64_attachments or []]
    return shown(message.text or "", names, styled=styled) | {"files": files}


async def kept_file(file: File, fetch: bool) -> dict[str, Any]:
    """An attachment signal-cli keeps; fetched, with its contents, as base64,
    unless it's too big, or signal-cli has it no longer."""
    found: dict[str, Any] = {
        "content_type": file.content_type,
        "filename": file.filename,
        "size": file.size,
    }
    if not fetch:
        return found
    if file.size is not None and file.size > chat_cli.MAX_ATTACHED:
        return found | {"too_big": True}
    try:
        data = await rest.attachment(file.id)
    except EXPECTED as e:
        logger.warning("Could not fetch an attachment: %s", describe(e))
        data = None
    if data is None:
        return found | {"missing": True}
    return found | {"base64": base64.b64encode(data).decode()}


async def entry_of(
    received: Received, names: access.Names, fetch: bool
) -> dict[str, Any]:
    """A message the bot received, as nejomibot-chat shows it: when, where,
    from whom, and what, with its files if fetched."""
    return {
        "at": received.at.astimezone(get_settings().tz).isoformat(timespec="seconds"),
        "chat": received.chat or None,
        "chat_name": names.of(received.chat) if received.chat else None,
        "sender": received.sender,
        "sender_name": names.of(received.number or received.sender, received.name),
        **shown(received.text, names, styled=True),
        "attachments": received.attachments,
        "files": [await kept_file(file, fetch) for file in received.files],
        "edited": received.edited,
    }


async def say(writer: asyncio.StreamWriter, said: dict[str, Any]) -> None:
    writer.write(json.dumps(said, ensure_ascii=False).encode() + b"\n")
    await writer.drain()


def attachment(attached: Attached, data: bytes) -> Attachment:
    """A file nejomibot-chat attached, as signalbot has one it downloaded,
    with a type and name that a data URL can have."""
    kind = attached.content_type
    return Attachment.model_validate(
        {
            "contentType": kind if CONTENT_TYPE.match(kind) else chat_cli.UNKNOWN,
            "filename": NOT_IN_NAMES.sub("_", attached.filename),
            "size": len(data),
            "isVoiceNote": False,
            "base64_content": base64.b64encode(data).decode(),
        }
    )


def for_chats(text: str, chats: list[int]) -> str:
    """A message for chats of /chats, as the direct chat takes it: its command
    run there, as /run does, if it starts with one, else posted there, as
    /msg does."""
    numbers = ",".join(map(str, chats))
    command = "/run" if known(canonical(text.strip())) else "/msg"
    return f"{command} {numbers} {text}"


async def answers_to(
    bot: SignalBot, request: Request, reader: asyncio.StreamReader
) -> list[dict[str, Any]]:
    """The bot's answers to the request's message, from the first admin in a
    direct chat with it, its files read after the request. Raises Refused."""
    if sum(each.size for each in request.attachments) > chat_cli.MAX_ATTACHED:
        raise Refused("The files are over 25 MB together.")
    attachments = [
        attachment(each, await reader.readexactly(each.size))
        for each in request.attachments
    ]
    sent = for_chats(request.text, request.chats) if request.chats else request.text
    text, styles = typed(sent)
    message = made_up(text, attachments=attachments or None, styles=styles or None)
    answers: list[SendMessage] = []
    token = to_terminal.set(answers)
    try:
        await timekeeper.handle(message)
    finally:
        to_terminal.reset(token)
    chat = message.source_number or message.source_uuid or ""
    sent = [for_chat(each, chat) for each in answers]
    mentions = any(MENTION.search(each.text or "") for each in sent)
    names = await access.names(bot) if mentions else access.Names()
    return [answer_of(each, names) for each in sent]


def in_chats(chats: list[Chat] | None) -> Callable[[Received], bool]:
    """Whether a message the bot received is one to show: any, without chats;
    else one in the chats, a group, or a direct chat with a person, by their
    Signal ID or number, as access.sent_by has them."""

    def wanted(received: Received) -> bool:
        if chats is None:
            return True
        if received.chat:
            return any(received.chat == chat_id for chat_id, _name in chats)
        return any(
            chat_id in (received.sender, received.number) for chat_id, _name in chats
        )

    return wanted


async def received(
    bot: SignalBot,
    request: Request,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """The latest messages the bot received, as many as asked for, oldest
    first; then, to follow them, each as it comes, until nejomibot-chat
    goes. For some of /chats' chats, only theirs, after the chats' names and
    how many of the latest come. Raises Refused."""
    chats: list[Chat] | None = None
    if request.chats:
        if isinstance(found := await chats_numbered(bot, request.chats), str):
            raise Refused(found)
        chats = found
    wanted = in_chats(chats)
    names = await access.names(bot)
    queue: asyncio.Queue[Received] = asyncio.Queue(BEHIND)
    # Both at once, so that none comes in between
    latest = [each for each in recent.latest() if wanted(each)]
    latest = latest[: request.recent or 0][::-1]
    if request.follow:
        recent.followers.add(queue)
    try:
        if chats is not None:
            those = [
                {"name": name, "group": access.is_group(chat_id)}
                for chat_id, name in chats
            ]
            await say(writer, {"chats": those, "recent": len(latest)})
        for each in latest:
            await say(writer, await entry_of(each, names, request.files))
        if request.follow:
            await follow(queue, names, request.files, reader, writer, wanted)
    finally:
        recent.followers.discard(queue)


async def follow(
    queue: asyncio.Queue[Received],
    names: access.Names,
    fetch: bool,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    wanted: Callable[[Received], bool],
) -> None:
    """Send each wanted message the queue gets, until nejomibot-chat goes, as
    it sends nothing more until then."""
    gone = asyncio.create_task(reader.read(1))
    try:
        while True:
            got = asyncio.create_task(queue.get())
            await asyncio.wait({got, gone}, return_when=asyncio.FIRST_COMPLETED)
            if not got.done():
                got.cancel()
                return
            if wanted(got.result()):
                await say(writer, await entry_of(got.result(), names, fetch))
    finally:
        gone.cancel()


def peer_uid(writer: asyncio.StreamWriter) -> int:
    """The user of the process at the other end."""
    connection = writer.get_extra_info("socket")
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, socket.SO_PEERCRED, CREDENTIALS.size
    )
    _pid, uid, _gid = CREDENTIALS.unpack(credentials)
    return uid


async def answer(
    bot: SignalBot, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Do what nejomibot-chat asks. Raises Refused."""
    try:
        request = Request.model_validate_json(await reader.readline())
    except ValueError as e:  # too long, or not as nejomibot-chat writes it
        logger.warning("nejomibot-chat sent what it doesn't: %s", type(e).__name__)
        raise Refused("That's no request of nejomibot-chat's.") from e
    if peer_uid(writer) not in (0, os.geteuid()):  # root, or the bot's own user
        logger.warning("Refused nejomibot-chat for another user")
        raise Refused("The bot answers only its own user, and root.")
    if request.recent or request.follow:
        await received(bot, request, reader, writer)
        return
    for each in await answers_to(bot, request, reader):
        await say(writer, each)


async def talk(
    bot: SignalBot, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Answer nejomibot-chat. Never raises."""
    try:
        # Once it has gone, nothing more is said
        with contextlib.suppress(ConnectionError, asyncio.IncompleteReadError):
            try:
                await answer(bot, reader, writer)
            except Refused as e:
                await say(writer, {"error": str(e)})
                await drain(reader)
            except Exception as e:
                logger.exception("Answering nejomibot-chat failed")
                await say(writer, {"error": f"Something went wrong: {describe(e)}"})
                await drain(reader)
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()


async def drain(reader: asyncio.StreamReader) -> None:
    """Read what nejomibot-chat still sends, as files after a request the bot
    refused, up to what a request may have, until it has sent all: a socket
    closed before it's read resets the connection, and nejomibot-chat would
    then miss why."""
    left = HEADER_LIMIT + chat_cli.MAX_ATTACHED
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(DRAIN_FOR):
            while left > 0 and (chunk := await reader.read(min(left, 64 * 1024))):
                left -= len(chunk)


class Listener:
    """nejomibot-chat's way to the bot: its socket, once signalbot is ready."""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None

    async def serve(self, bot: SignalBot) -> None:
        await bot.wait_until_ready()
        try:
            self.server = await asyncio.start_unix_server(
                functools.partial(talk, bot), path=chat_cli.SOCKET, limit=HEADER_LIMIT
            )
        except OSError as e:
            logger.warning("nejomibot-chat can't reach the bot: %r", e)

    async def stop(self) -> None:
        if (server := self.server) is not None:
            server.close()
            server.close_clients()  # as one that follows would stay
            await server.wait_closed()
            self.server = None


listener = Listener()


def start(bot: SignalBot) -> None:
    """Answer nejomibot-chat, once signalbot is ready."""
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        listener.serve,
        args=[bot],
        id="terminal-serve",
        misfire_grace_time=None,
        replace_existing=True,
    )


async def stop() -> None:
    """Stop answering nejomibot-chat, as the bot stops."""
    await listener.stop()
