"""The bot's own Signal profile, for the admins in direct chats: /profile shows
it, and /name, /about, /avatar and /username change it.

A profile has a name, an About text and an avatar; the username belongs to the
account. signalbot can neither read nor change them, so these commands ask
signal-cli-rest-api (rest.py). Its profile update sets the given name and
About, and removes the avatar unless the picture comes along again, so every
change sends the current avatar back. It can't change the family name or the
emoji before About: whatever they are, they stay.

A new avatar is the picture sent with /avatar, fetched from
signal-cli-rest-api, made square without its metadata, and uploaded. That
needs signal-cli to keep the pictures sent to the bot, which it doesn't with
JSON_RPC_IGNORE_ATTACHMENTS=true.
"""

import asyncio
import io
import logging
import re
from dataclasses import dataclass

from PIL import Image, ImageOps
from signalbot import Attachment, DataMessageContext, SignalBot

from . import rest
from .account import Contact, fetch_recipients, full_name
from .account import Profile as ContactProfile
from .commands import Command, Handler, answer, argument
from .config import get_settings
from .i18n import _, format_file_size, ngettext
from .messages import escape
from .photos import open_image

logger = logging.getLogger(__name__)

REMOVE = "remove"

# Signal's limits: a name as the Android app cuts it, About as the apps let it
# be typed, and what an encrypted profile field holds
NAME_MAX_BYTES = 128
ABOUT_MAX_CHARACTERS = 140
ABOUT_MAX_BYTES = 512
# A nickname, and maybe the number Signal adds to it: mybot, or mybot.42
VALID_USERNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{2,31}(\.[0-9]{2,9})?$")

AVATAR_SIDE = 1024  # pixels, as the Signal Android app makes avatars
MAX_PICTURE_BYTES = 30 * 1024 * 1024  # a bigger file is no avatar
JPEG_QUALITY = 90


def name_usage() -> str:
    return _("Send /name <new name>.")


def about_usage() -> str:
    return _("Send /about <text>, or /about remove.")


def avatar_usage() -> str:
    return _("Send a picture with /avatar as its caption, or /avatar remove.")


def username_usage() -> str:
    return _(
        "Send /username <name>, or /username remove. A name is 3 to 32 letters, "
        "digits or _, not starting with a digit; Signal adds a number to it, "
        "like mybot.42, unless you give one."
    )


def no_name() -> str:
    return _("Give the bot a name first: Signal's profile needs one.") + (
        f" {name_usage()}"
    )


def not_kept() -> str:
    return _(
        "signal-cli didn't keep the picture, so it can't be the avatar. It keeps "
        "none while it runs with JSON_RPC_IGNORE_ATTACHMENTS=true; "
        "signal-account.sh can set the avatar from a file instead."
    )


@dataclass(frozen=True)
class AvatarImage:
    data: bytes
    format: str  # JPEG, or PNG to keep see-through parts
    side: int  # pixels; avatars are square


async def fetch_me() -> Contact:
    """The bot itself, among the recipients signal-cli knows."""
    account = get_settings().account
    me = next((c for c in await fetch_recipients() if c.is_one_of({account})), None)
    if me is not None:
        return me
    if account.startswith("+"):
        return Contact(number=account)
    return Contact(uuid=account)  # an account without a number


def profile_of(me: Contact) -> ContactProfile:
    return me.profile or ContactProfile()


def name_of(me: Contact) -> str | None:
    profile = profile_of(me)
    return full_name(profile.given_name, profile.lastname)


class AvatarLost(Exception):
    """The profile has an avatar that can't be had, to send back."""


async def current_avatar(me: Contact) -> bytes | None:
    """The avatar as it is, to send back with a change, which would remove
    it otherwise. Raises AvatarLost if there's one signal-cli can't give."""
    if not profile_of(me).has_avatar:
        return None
    if avatar := await rest.avatar(me.uuid or me.number or get_settings().account):
        return avatar
    raise AvatarLost(
        _(
            "signal-cli can't give back the avatar, and the change would remove "
            "it: /avatar remove first, then set it again."
        )
    )


async def change(me: Contact, given_name: str, about: str | None) -> None:
    """Set the given name, and About unless it's None, keeping the avatar."""
    avatar = await current_avatar(me)
    await rest.update_profile(given_name, about=about, avatar=avatar)


def is_remove(value: str) -> bool:
    return value.casefold() == REMOVE


def too_long(size: int, limit: int) -> str:
    return _(
        "That's {size} bytes, and Signal holds at most {limit}: letters such as "
        "å and é take two each, emoji four."
    ).format(size=size, limit=limit)


def about_text(profile: ContactProfile) -> str:
    if profile.about:
        return _("About: {about}").format(about=profile.about)
    return _("No About")


async def name_command(text: str | None) -> str:
    me = await fetch_me()
    if not (name := argument(text)):
        current = name_of(me)
        shown = _("Name: {name}").format(name=current) if current else _("No name")
        return f"{shown}\n{name_usage()}"
    if is_remove(name):
        return (
            _("A Signal profile needs a name, so it can only be changed.")
            + f" {name_usage()}"
        )
    if (size := len(name.encode())) > NAME_MAX_BYTES:
        return too_long(size, NAME_MAX_BYTES)
    await change(me, name, about=None)
    return "✅ " + _("Name: {name}").format(name=name_of(await fetch_me()))


async def about_command(text: str | None) -> str:
    me = await fetch_me()
    if not (about := argument(text)):
        return f"{about_text(profile_of(me))}\n{about_usage()}"
    if not (given_name := profile_of(me).given_name):
        return no_name()
    if is_remove(about):
        about = ""
    elif len(about) > ABOUT_MAX_CHARACTERS:
        return _(
            "About holds at most {limit} characters in Signal's apps, and "
            "that's {count}."
        ).format(limit=ABOUT_MAX_CHARACTERS, count=len(about))
    elif (size := len(about.encode())) > ABOUT_MAX_BYTES:
        return too_long(size, ABOUT_MAX_BYTES)
    await change(me, given_name, about)
    if about:
        return "✅ " + _("About: {about}").format(about=about)
    return _("✅ No About now.")


def has_see_through(image: Image.Image) -> bool:
    if not image.has_transparency_data:
        return False
    lowest = image.convert("RGBA").getchannel("A").getextrema()[0]
    return isinstance(lowest, float | int) and lowest < 255


def make_avatar(picture: bytes) -> AvatarImage:
    """The picture as an avatar: upright, its middle square at most
    AVATAR_SIDE pixels wide, and without the original's metadata, such as
    where it was taken. A JPEG, or a PNG when it has see-through parts, as a
    logo may. Blocking."""
    with open_image(io.BytesIO(picture)) as opened:
        upright = ImageOps.exif_transpose(opened)
    see_through = has_see_through(upright)
    image = upright.convert("RGBA" if see_through else "RGB")
    side = min(image.width, image.height, AVATAR_SIDE)
    square = ImageOps.fit(image, (side, side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    if see_through:
        square.save(buffer, "PNG", optimize=True)
        return AvatarImage(buffer.getvalue(), "PNG", side)
    square.save(buffer, "JPEG", quality=JPEG_QUALITY)
    return AvatarImage(buffer.getvalue(), "JPEG", side)


async def take_attachment(bot: SignalBot, picture: Attachment) -> bytes | None:
    """The picture, which is then deleted from signal-cli's disk. None if
    signal-cli didn't keep it."""
    if not picture.local_filename:
        return None
    if (data := await rest.attachment(picture.local_filename)) is None:
        return None
    try:
        await bot.attachments.delete(picture)
    except Exception as e:
        logger.warning("Could not delete attachment %s: %r", picture.local_filename, e)
    return data


async def set_avatar(bot: SignalBot, picture: Attachment) -> str:
    if picture.size and picture.size > MAX_PICTURE_BYTES:
        return _(
            "That picture is {size}, too big for an avatar: send one under {limit}."
        ).format(
            size=format_file_size(picture.size),
            limit=format_file_size(MAX_PICTURE_BYTES),
        )
    if not (given_name := profile_of(await fetch_me()).given_name):
        return no_name()
    if not (data := await take_attachment(bot, picture)):
        return not_kept()
    try:
        avatar = await asyncio.to_thread(make_avatar, data)
    except Exception as e:
        logger.warning("Could not read the picture for the avatar: %r", e)
        return _("That picture can't be read: {error}").format(error=e)
    await rest.update_profile(given_name, about=None, avatar=avatar.data)
    return _("✅ New avatar: {size} {format}, {bytes}.").format(
        size=f"{avatar.side}x{avatar.side}",
        format=avatar.format,
        bytes=format_file_size(len(avatar.data)),
    )


async def remove_avatar() -> str:
    if not (given_name := profile_of(await fetch_me()).given_name):
        return no_name()
    await rest.update_profile(given_name, about=None, avatar=None)
    return _("✅ Avatar removed.")


async def avatar_command(
    bot: SignalBot, text: str | None, attachments: list[Attachment] | None
) -> str:
    wanted = argument(text)
    if is_remove(wanted):
        return await remove_avatar()
    pictures = [
        a for a in attachments or [] if (a.content_type or "").startswith("image/")
    ]
    if wanted:
        return avatar_usage()
    if not pictures:
        if attachments:
            return _("That isn't a picture.") + f" {avatar_usage()}"
        return avatar_usage()
    if len(pictures) > 1:
        return ngettext(
            "That's {count} picture: send just one with /avatar.",
            "That's {count} pictures: send just one with /avatar.",
            len(pictures),
        ).format(count=len(pictures))
    return await set_avatar(bot, pictures[0])


async def username_command(text: str | None) -> str:
    wanted = argument(text).removeprefix("@")
    if not wanted:
        current = (await fetch_me()).username
        if current:
            shown = _("Username: {username}").format(username=f"@{current}")
        else:
            shown = _("No username")
        return f"{shown}\n{username_usage()}"
    if is_remove(wanted):
        await rest.delete_username()
        return _("✅ Username removed.")
    if not VALID_USERNAME.match(wanted):
        return (
            _("{username} can't be a Signal username.").format(username=wanted)
            + f" {username_usage()}"
        )
    try:
        answer = await rest.set_username(wanted)
    except rest.RestError as e:
        # signal-cli-rest-api doesn't pass on why Signal said no
        logger.warning("Username %s refused: %s", wanted, e)
        return _(
            "Signal turned {username} down: it's most likely taken, or not "
            "allowed. Try another."
        ).format(username=wanted)
    text = "✅ " + _("Username: {username}").format(username=f"@{answer['username']}")
    if link := answer.get("username_link"):
        text += "\n" + _("A link that starts a chat with the bot: {link}").format(
            link=link
        )
    return text


def profile_text(me: Contact) -> str:
    """Styled: the name in bold, the rest as is."""
    profile = profile_of(me)
    name = name_of(me)
    lines = [
        "💬 " + about_text(profile),
        "🔗 "
        + (
            _("Username: {username}").format(username=f"@{me.username}")
            if me.username
            else _("No username")
        ),
        "🖼️ " + (_("Avatar: yes") if profile.has_avatar else _("No avatar")),
        (
            "📞 " + _("Number: {number}").format(number=me.number)
            if me.number
            else "🆔 " + _("Signal ID: {id}").format(id=me.uuid)
        ),
        "",
        _("Change them with /name, /about, /avatar and /username."),
    ]
    shown = (
        f"**{escape(name)}**"
        if name
        else escape(_("No name, so Signal shows the number"))
    )
    return "\n".join([f"🪪 {shown}", *map(escape, lines)])


async def show_profile() -> str:
    return profile_text(await fetch_me())


# A change waits for Signal's servers, so they're slow


class Profile(Handler):
    commands = (Command("/profile"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, show_profile, styled=True)


class Name(Handler):
    commands = (Command("/name", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, lambda: name_command(context.message.text), slow=True)


class About(Handler):
    commands = (Command("/about", more=True, subcommands=(REMOVE,)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, lambda: about_command(context.message.text), slow=True)


class Avatar(Handler):
    commands = (Command("/avatar", more=True, subcommands=(REMOVE,)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        await answer(
            context,
            lambda: avatar_command(context.bot, message.text, message.attachments),
            slow=True,
        )


class Username(Handler):
    commands = (Command("/username", more=True, subcommands=(REMOVE,)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, lambda: username_command(context.message.text), slow=True)
