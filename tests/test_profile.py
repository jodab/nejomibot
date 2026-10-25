import base64
import hashlib
import io
from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web
from helpers import ME, ME_ID, FakeApi
from PIL import Image
from signalbot import (
    Attachment,
    DataMessage,
    DataMessageContext,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import commands, profile
from nejomibot.account import Contact
from nejomibot.config import get_settings
from nejomibot.profile import (
    Name,
    Profile,
    about_command,
    avatar_command,
    make_avatar,
    name_command,
    not_kept,
    profile_text,
    take_attachment,
    username_command,
)

ADMIN = "+46700000001"
LINK = "https://signal.me/#eu/abc"
AVATAR = b"the avatar as it is"
PROFILES = f"/v1/profiles/{ME}"
USERNAME = f"/v1/accounts/{ME}/username"
TAKEN = {"taken", "nejomi.07"}  # as Signal turns them down


class Profiles:
    """The bot's own profile in the fake signal-cli-rest-api, which its updates
    change as signal-cli-rest-api's do: they set the given name, About if
    given, and the avatar, which goes unless it's sent along."""

    def __init__(self, api: FakeApi) -> None:
        self.api = api
        self.avatar: bytes | None = AVATAR
        self.profile.update(
            given_name="Mybot", lastname="Bot", about="The best bot.", has_avatar=True
        )
        api.route("PUT", PROFILES, self.update)
        api.route("GET", f"/v1/contacts/{ME}/{ME_ID}/avatar", self.get_avatar)
        api.route("POST", USERNAME, self.set_username)
        api.route("DELETE", USERNAME, self.delete_username)

    @property
    def me(self) -> dict[str, Any]:
        recipients = self.api.responses[f"/v1/contacts/{ME}?all"]
        return next(r for r in recipients if r["number"] == ME)

    @property
    def profile(self) -> dict[str, Any]:
        return self.me["profile"]

    def updates(self) -> list[dict[str, Any]]:
        return self.api.bodies("PUT", PROFILES)

    def attach(self, attachment_id: str, data: bytes) -> None:
        async def get(request: web.Request) -> web.Response:
            return web.Response(body=data, content_type="image/jpeg")

        self.api.route("GET", f"/v1/attachments/{attachment_id}", get)

    async def update(self, request: web.Request) -> web.Response:
        update = await request.json()
        self.profile["given_name"] = update["name"]
        if "about" in update:
            self.profile["about"] = update["about"]
        avatar = update.get("base64_avatar")
        self.avatar = base64.b64decode(avatar) if avatar else None
        self.profile["has_avatar"] = self.avatar is not None
        return web.Response(status=204)

    async def get_avatar(self, request: web.Request) -> web.Response:
        if self.avatar is None:
            return web.json_response({"error": "No avatar"}, status=404)
        return web.Response(body=self.avatar, content_type="image/png")

    async def set_username(self, request: web.Request) -> web.Response:
        wanted = (await request.json())["username"]
        if wanted in TAKEN:
            return web.json_response(
                {"error": "invalid signal-cli response"}, status=400
            )
        self.me["username"] = wanted if "." in wanted else f"{wanted}.42"
        return web.json_response(
            {"username": self.me["username"], "username_link": LINK}
        )

    async def delete_username(self, request: web.Request) -> web.Response:
        self.me["username"] = None
        return web.Response(status=204)


@pytest.fixture
def profiles(signal_api: FakeApi) -> Profiles:
    return Profiles(signal_api)


def encoded(image: Image.Image, image_format: str, **options: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def picture(attachment_id: str, content_type: str = "image/jpeg") -> Attachment:
    return Attachment.model_validate(
        {"contentType": content_type, "id": attachment_id, "isVoiceNote": False}
    )


def halves(size: tuple[int, int]) -> Image.Image:
    """Red on the left, blue on the right."""
    image = Image.new("RGB", size, "blue")
    image.paste("red", (0, 0, size[0] // 2, size[1]))
    return image


def color_at(image: Image.Image, xy: tuple[int, int]) -> str:
    red, _, blue = cast(tuple[int, int, int], image.convert("RGB").getpixel(xy))
    return "red" if red > blue else "blue"


# The profile


def test_profile_text() -> None:
    me = Contact.model_validate(
        {
            "number": ME,
            "username": "mybot.42",
            "profile": {
                "given_name": "Mybot*",
                "lastname": "Bot",
                "about": "The best bot.",
                "has_avatar": True,
            },
        }
    )
    assert profile_text(me).splitlines() == [
        "🪪 **Mybot\\* Bot**",
        "💬 About: The best bot.",
        "🔗 Username: @mybot.42",
        "🖼️ Avatar: yes",
        f"📞 Number: {ME}",
        "",
        "Change them with /name, /about, /avatar and /username.",
    ]


def test_profile_text_without_a_profile() -> None:
    me = Contact.model_validate({"number": ME, "username": None, "profile": None})
    assert profile_text(me).splitlines()[:4] == [
        "🪪 No name, so Signal shows the number",
        "💬 No About",
        "🔗 No username",
        "🖼️ No avatar",
    ]


def test_profile_text_without_a_number() -> None:
    me = Contact.model_validate({"uuid": ME_ID, "username": "mybot.42"})
    lines = profile_text(me).splitlines()
    assert f"🆔 Signal ID: {ME_ID}" in lines
    assert "🔗 Username: @mybot.42" in lines


def test_profile_text_without_a_number_or_a_username() -> None:
    lines = profile_text(Contact(uuid=ME_ID)).splitlines()
    assert lines[0] == "🪪 No name"
    assert "⚠️ No username: without a phone number, nobody can find the bot" in lines
    # With a number, people can find the bot by that
    assert "🔗 No username" in profile_text(Contact(number=ME)).splitlines()


@pytest.mark.parametrize(
    ("account", "known"),
    [(ME, Contact(number=ME)), (ME_ID, Contact(uuid=ME_ID))],
)
async def test_the_bot_is_itself_before_signal_cli_knows_it(
    monkeypatch: pytest.MonkeyPatch, account: str, known: Contact
) -> None:
    async def nobody() -> list[Contact]:
        return []

    monkeypatch.setenv("NEJOMIBOT_ACCOUNT", account)
    get_settings.cache_clear()
    monkeypatch.setattr(profile, "fetch_recipients", nobody)
    assert await profile.fetch_me() == known


# /name and /about, which keep the avatar


async def test_name_sets_the_given_name(profiles: Profiles) -> None:
    # signal-cli-rest-api can't change the family name, so it stays
    assert await name_command("/name  Mybot\nBoten") == "✅ Name: Mybot Boten Bot"
    assert profiles.updates() == [
        {"name": "Mybot Boten", "base64_avatar": base64.b64encode(AVATAR).decode()}
    ]
    assert profiles.avatar == AVATAR


async def test_name_alone_says_what_it_is(profiles: Profiles) -> None:
    assert await name_command("/name") == "Name: Mybot Bot\nSend /name <new name>."
    assert profiles.updates() == []


@pytest.mark.parametrize("name", ["remove", "å" * 65])
async def test_name_that_cant_be(profiles: Profiles, name: str) -> None:
    assert not (await name_command(f"/name {name}")).startswith("✅")
    assert profiles.updates() == []


async def test_about_keeps_the_name_and_avatar(profiles: Profiles) -> None:
    assert await about_command("/about Weather and photos") == (
        "✅ About: Weather and photos"
    )
    assert profiles.updates() == [
        {
            "name": "Mybot",
            "about": "Weather and photos",
            "base64_avatar": base64.b64encode(AVATAR).decode(),
        }
    ]
    assert profiles.avatar == AVATAR


async def test_about_without_an_avatar(profiles: Profiles) -> None:
    profiles.avatar = None
    profiles.profile["has_avatar"] = False
    await about_command("/about Hi")
    assert profiles.updates() == [{"name": "Mybot", "about": "Hi"}]


async def test_a_change_wont_lose_the_avatar(profiles: Profiles) -> None:
    # The profile has one, but signal-cli can't give it back
    profiles.avatar = None
    with pytest.raises(profile.AvatarLost, match="/avatar remove first"):
        await about_command("/about Hi")
    assert profiles.updates() == []


async def test_about_remove(profiles: Profiles) -> None:
    assert await about_command("/about Remove") == "✅ No About now."
    assert profiles.updates()[0]["about"] == ""


async def test_about_alone_says_what_it_is(profiles: Profiles) -> None:
    assert await about_command("/about") == (
        "About: The best bot.\nSend /about <text>, or /about remove."
    )


async def test_about_needs_a_name(profiles: Profiles) -> None:
    profiles.profile.update(given_name=None, lastname=None)
    assert (await about_command("/about Hi")).startswith("Give the bot a name first")
    assert profiles.updates() == []


@pytest.mark.parametrize("about", ["x" * 141, "😀" * 129])
async def test_about_too_long(profiles: Profiles, about: str) -> None:
    assert "at most" in await about_command(f"/about {about}")
    assert profiles.updates() == []


# /username


async def test_username_from_a_nickname(profiles: Profiles) -> None:
    assert await username_command("/username @mybot") == (
        f"✅ Username: @mybot.42\nA link that starts a chat with the bot: {LINK}"
    )
    assert profiles.api.bodies("POST", USERNAME) == [{"username": "mybot"}]
    assert (await username_command("/username")).startswith("Username: @mybot.42\n")


async def test_username_with_its_number(profiles: Profiles) -> None:
    assert (await username_command("/username mybot.07")).startswith(
        "✅ Username: @mybot.07\n"
    )


@pytest.mark.parametrize("wanted", ["ab", "1abc", "my bot", "mybot.1", "a-b-c"])
async def test_username_that_cant_be(profiles: Profiles, wanted: str) -> None:
    assert "can't be a Signal username" in await username_command(f"/username {wanted}")
    assert profiles.api.bodies("POST", USERNAME) == []


async def test_username_taken_says_what_is_likely(profiles: Profiles) -> None:
    assert await username_command("/username taken") == (
        "Signal turned taken down: it's most likely taken, or not allowed. Try another."
    )


async def test_username_remove(profiles: Profiles) -> None:
    profiles.me["username"] = "mybot.42"
    assert await username_command("/username remove") == "✅ Username removed."
    assert profiles.me["username"] is None


# /avatar


def test_avatar_is_upright_square_and_without_metadata() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # turned: shows rotated a quarter clockwise
    exif[0x010E] = "Where it was taken"
    # Stored 3000x2000, red left: shows 2000x3000, red on top
    photo = encoded(halves((3000, 2000)), "JPEG", exif=exif.tobytes())

    avatar = make_avatar(photo)

    image = Image.open(io.BytesIO(avatar.data))
    assert (avatar.format, avatar.side) == ("JPEG", 1024)
    assert (image.format, image.size) == ("JPEG", (1024, 1024))
    assert color_at(image, (512, 10)) == "red"
    assert color_at(image, (512, 1013)) == "blue"
    assert not image.getexif()


def test_avatar_isnt_made_bigger() -> None:
    avatar = make_avatar(encoded(halves((300, 500)), "PNG"))
    assert (avatar.format, avatar.side) == ("JPEG", 300)


def test_avatar_keeps_see_through_parts() -> None:
    logo = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    logo.paste((255, 0, 0, 255), (100, 100, 300, 300))
    avatar = make_avatar(encoded(logo, "PNG"))
    image = Image.open(io.BytesIO(avatar.data))
    assert (avatar.format, image.mode) == ("PNG", "RGBA")
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)


async def test_avatar_from_a_picture(bot: SignalBot, profiles: Profiles) -> None:
    profiles.attach("pic.jpg", encoded(halves((1600, 1200)), "JPEG"))

    text = await avatar_command(bot, "/avatar", [picture("pic.jpg")])

    assert text.startswith("✅ New avatar: 1024x1024 JPEG, ")
    # The given name goes along, as the update sets it; About isn't sent, so
    # it stays
    [update] = profiles.updates()
    assert (set(update), update["name"]) == ({"name", "base64_avatar"}, "Mybot")
    assert profiles.avatar is not None
    assert Image.open(io.BytesIO(profiles.avatar)).size == (1024, 1024)
    # Deleted from signal-cli's disk, through signalbot
    assert profiles.api.bodies("DELETE", "/v1/attachments/pic.jpg") == [None]


async def test_avatar_needs_a_kept_picture(bot: SignalBot, profiles: Profiles) -> None:
    # Not on signal-cli's disk, as with JSON_RPC_IGNORE_ATTACHMENTS=true
    answer = await avatar_command(bot, "/avatar", [picture("gone.jpg")])
    assert answer == not_kept()
    assert profiles.updates() == []


async def test_avatar_needs_a_name(bot: SignalBot, profiles: Profiles) -> None:
    profiles.profile.update(given_name=None, lastname=None)
    profiles.attach("pic.jpg", encoded(halves((100, 100)), "JPEG"))
    answer = await avatar_command(bot, "/avatar", [picture("pic.jpg")])
    assert answer.startswith("Give the bot a name first")
    assert profiles.updates() == []


async def test_avatar_that_cant_be_read(bot: SignalBot, profiles: Profiles) -> None:
    profiles.attach("pic.jpg", b"not a picture")
    text = await avatar_command(bot, "/avatar", [picture("pic.jpg")])
    assert text.startswith("That picture can't be read")
    assert profiles.updates() == []


@pytest.mark.parametrize(
    ("text", "attachments", "answer"),
    [
        ("/avatar", None, "Send a picture with /avatar"),
        ("/avatar", [picture("a.pdf", "application/pdf")], "That isn't a picture"),
        ("/avatar please", [picture("a.jpg")], "Send a picture with /avatar"),
        ("/avatar", [picture("a.jpg"), picture("b.jpg")], "That's 2 pictures"),
    ],
)
async def test_avatar_usage(
    bot: SignalBot,
    profiles: Profiles,
    text: str,
    attachments: list[Attachment] | None,
    answer: str,
) -> None:
    assert (await avatar_command(bot, text, attachments)).startswith(answer)
    assert profiles.updates() == []


async def test_avatar_remove(bot: SignalBot, profiles: Profiles) -> None:
    assert await avatar_command(bot, "/avatar remove", None) == "✅ Avatar removed."
    assert profiles.updates() == [{"name": "Mybot"}]
    assert profiles.avatar is None


async def test_take_attachment(bot: SignalBot, profiles: Profiles) -> None:
    profiles.attach("a.jpg", b"a")
    assert await take_attachment(bot, picture("a.jpg")) == b"a"
    # Deleted from signal-cli's disk, through signalbot
    assert profiles.api.bodies("DELETE", "/v1/attachments/a.jpg") == [None]
    assert await take_attachment(bot, picture("gone.jpg")) is None


# The handlers


def context_of(bot: SignalBot, text: str) -> DataMessageContext:
    message = DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=1,
        source=ADMIN,
        source_number=ADMIN,
        text=text,
    )
    return DataMessageContext(bot, message)


@pytest.fixture
def replies(monkeypatch: pytest.MonkeyPatch) -> list[SendMessage]:
    sent: list[SendMessage] = []

    async def reply(_: DataMessageContext, message: SendMessage) -> None:
        sent.append(message)

    monkeypatch.setattr(commands, "reply", reply)
    return sent


async def test_profile_replies_styled(
    bot: SignalBot, profiles: Profiles, replies: list[SendMessage]
) -> None:
    await Profile().handle_data_message(context_of(bot, "/profile"))
    [message] = replies
    assert message.text_mode is TextMode.STYLED
    assert (message.text or "").startswith("🪪 **Mybot Bot**\n💬 About: The best bot.")


async def test_failure_is_answered(
    bot: SignalBot, profiles: Profiles, replies: list[SendMessage]
) -> None:
    async def fail(request: web.Request) -> web.Response:
        return web.json_response({"error": "Signal says no"}, status=400)

    profiles.api.route("PUT", PROFILES, fail)
    await Name().handle_data_message(context_of(bot, "/name Mybot"))
    [message] = replies
    assert message.text == "Something went wrong: Signal says no"


# bot.txt


def new_account(profiles: Profiles) -> None:
    """As a new account's: no name, About, avatar or username."""
    profiles.profile.update(
        given_name=None, lastname=None, about=None, has_avatar=False
    )
    profiles.avatar = None
    profiles.me["username"] = None


def bot_txt() -> list[str]:
    """bot.txt's lines but its comments."""
    text = get_settings().data_file("bot.txt").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if not line.startswith("#")]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """config.toml's bot_* settings, with a picture for the avatar."""
    picture = tmp_path / "logo.jpg"
    Image.new("RGB", (1200, 800), "orange").save(picture)
    monkeypatch.setenv("NEJOMIBOT_BOT_NAME", "Nejomi")
    monkeypatch.setenv("NEJOMIBOT_BOT_ABOUT", "Weather and photos")
    monkeypatch.setenv("NEJOMIBOT_BOT_AVATAR", str(picture))
    monkeypatch.setenv("NEJOMIBOT_BOT_USERNAME", "@nejomi")
    get_settings.cache_clear()
    return picture


@pytest.mark.usefixtures("configured")
async def test_the_settings_set_a_new_accounts_profile(profiles: Profiles) -> None:
    new_account(profiles)
    await profile.set_kept_profile()
    [update] = profiles.updates()
    assert (update["name"], update["about"]) == ("Nejomi", "Weather and photos")
    uploaded = base64.b64decode(update["base64_avatar"])
    assert Image.open(io.BytesIO(uploaded)).size == (800, 800)  # made square
    assert profiles.api.bodies("POST", USERNAME) == [{"username": "nejomi"}]
    assert get_settings().data_file("bot-avatar.jpg").read_bytes() == uploaded
    assert bot_txt() == [
        "name Nejomi",
        "about Weather and photos",
        f"avatar bot-avatar.jpg {sha256(uploaded)}",
        "username nejomi.42",
    ]
    # The next start finds the profile as bot.txt has it
    await profile.set_kept_profile()
    assert len(profiles.updates()) == 1
    assert len(profiles.api.bodies("POST", USERNAME)) == 1


@pytest.mark.usefixtures("configured")
async def test_bot_txt_comes_before_the_settings(profiles: Profiles) -> None:
    get_settings().data_file("bot.txt").write_text("name Mybot\nusername\n")
    await profile.set_kept_profile()
    # About and the avatar from the settings, as bot.txt has neither
    [update] = profiles.updates()
    assert (update["name"], update["about"]) == ("Mybot", "Weather and photos")
    assert "base64_avatar" in update
    # bot.txt's empty username removes it
    assert profiles.api.bodies("DELETE", USERNAME) == [None]
    assert "username" in bot_txt()


async def test_a_taken_username_gets_the_number_signal_gives(
    profiles: Profiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_BOT_USERNAME", "nejomi.07")
    get_settings.cache_clear()
    await profile.set_kept_profile()
    assert profiles.api.bodies("POST", USERNAME) == [
        {"username": "nejomi.07"},
        {"username": "nejomi"},
    ]
    assert bot_txt() == ["username nejomi.42"]


async def test_the_commands_keep_what_they_set(profiles: Profiles) -> None:
    await name_command("/name Nejomi")
    await about_command("/about remove")
    await username_command("/username nejomi")
    assert bot_txt() == ["name Nejomi", "about", "username nejomi.42"]


async def test_an_edited_bot_txt_is_set(profiles: Profiles) -> None:
    get_settings().data_file("bot.txt").write_text("name Other\nabout New\n")
    await profile.set_kept_profile()
    [update] = profiles.updates()
    assert (update["name"], update["about"]) == ("Other", "New")
    assert base64.b64decode(update["base64_avatar"]) == AVATAR  # as it was


async def test_a_new_picture_for_the_avatar_is_set(profiles: Profiles) -> None:
    settings = get_settings()
    # bot.txt names the picture as it was set, and it's been replaced since
    Image.new("RGB", (64, 64), "blue").save(settings.data_file("bot-avatar.jpg"))
    settings.data_file("bot.txt").write_text(
        f"avatar bot-avatar.jpg {sha256(b'old')}\n"
    )
    await profile.set_kept_profile()
    [update] = profiles.updates()
    uploaded = base64.b64decode(update["base64_avatar"])
    assert bot_txt() == [f"avatar bot-avatar.jpg {sha256(uploaded)}"]
    # As set, it's left alone
    await profile.set_kept_profile()
    assert len(profiles.updates()) == 1


async def test_an_avatar_it_cant_read_leaves_the_rest(
    profiles: Profiles, caplog: pytest.LogCaptureFixture
) -> None:
    get_settings().data_file("bot.txt").write_text("name Other\navatar gone.jpg\n")
    await profile.set_kept_profile()
    [update] = profiles.updates()
    assert update["name"] == "Other"
    assert base64.b64decode(update["base64_avatar"]) == AVATAR
    assert "Could not read the avatar" in caplog.text
