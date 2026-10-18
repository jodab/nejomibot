from typing import Any, cast

import pytest
from helpers import ALICE, text_styles
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import commands, specials
from nejomibot.commands import known
from nejomibot.config import get_settings
from nejomibot.fortune import FORTUNES_DIR, read_fortunes
from nejomibot.specials import (
    HEADER,
    Part,
    Specials,
    check_name,
    headed,
    own_specials,
    parse_parts,
)
from nejomibot.styles import styles_of
from nejomibot.timers import Timekeeper, check_commands

ADMIN = "+46700000009"


class Chat:
    """An admin's direct chat with the bot: what it answers there, and the
    commands the specials run, which answer as below."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.replies: list[SendMessage] = []
        self.ran: list[str] = []
        self.keeper = Timekeeper()
        monkeypatch.setattr(commands, "reply", self.reply)
        monkeypatch.setattr(commands, "mark_read", self.nothing)
        monkeypatch.setattr(commands, "show_typing", self.nothing)
        monkeypatch.setattr(self.keeper, "answers_to", self.answers_to)
        monkeypatch.setattr(specials, "timekeeper", self.keeper)

    async def reply(self, context: DataMessageContext, message: SendMessage) -> None:
        self.replies.append(message)

    async def nothing(self, context: DataMessageContext) -> None:
        pass

    async def answers_to(self, command: str) -> list[SendMessage]:
        """Two answers to /status, as it has; one to the rest."""
        self.ran.append(command)
        if command == "/status":
            return [SendMessage(text="checks"), SendMessage(text="details")]
        return [SendMessage(text=f"{command}!")]

    async def send(
        self, text: str, *styled: tuple[str, str], edit: bool = False
    ) -> list[str]:
        """What the bot answers the message, as text. styled are words of it
        formatted in Signal, and how."""
        fields: dict[str, Any] = {
            "server_delivered_timestamp": 0,
            "server_received_timestamp": 0,
            "timestamp": 2,
            "source_number": ADMIN,
            "text": text,
            "text_styles": text_styles(text, *styled) or None,
        }
        message = (
            EditMessage(**fields, target_sent_timestamp=1)
            if edit
            else DataMessage(**fields)
        )
        self.replies.clear()
        await Specials().handle_data_message(
            DataMessageContext(cast(SignalBot, None), message)
        )
        return [reply.text or "" for reply in self.replies]


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> Chat:
    return Chat(monkeypatch)


# The two the bot comes with


@pytest.mark.usefixtures("swedish")
async def test_the_daily_post(chat: Chat, monkeypatch: pytest.MonkeyPatch) -> None:
    async def weather_message() -> str:
        return "Vädret"

    async def photo_message(
        caption: str = "", *, track_sent: bool = False
    ) -> SendMessage:
        return SendMessage(text=f"{caption} (from the round: {track_sent})")

    monkeypatch.setattr(specials, "weather_message", weather_message)
    monkeypatch.setattr(specials, "photo_message", photo_message)
    # By its Swedish name, as an admin sends it
    assert await chat.send("/dagensbild") == [
        "Vädret",
        "Dagens bild! (from the round: True)",
    ]


@pytest.mark.usefixtures("swedish")
async def test_the_daily_quote(chat: Chat) -> None:
    [text] = await chat.send("/dagenscitat")
    assert chat.replies[0].text_mode == TextMode.STYLED
    heading, quote = text.split("\n\n", 1)
    assert heading == "**Dagens ordspråk/citat:**"
    # It has no marks to escape
    assert quote in read_fortunes(FORTUNES_DIR / "fortunes_svenska")


async def test_the_daily_quote_keeps_its_library(
    chat: Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fortune_library is /fortune's alone."""
    monkeypatch.setenv("NEJOMIBOT_FORTUNE_LIBRARY", "startrek")
    get_settings.cache_clear()
    [text] = await chat.send("/dailyquote")
    quote = text.split("\n\n", 1)[1]
    assert quote in read_fortunes(FORTUNES_DIR / "fortunes_svenska")


# The admins' own


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        (
            "Joke of the day: /fortune cookie",
            [Part("Joke of the day:", "/fortune cookie")],
        ),
        (
            "/weather; The bins go out!",
            [Part("", "/weather"), Part("The bins go out!")],
        ),
        # Line breaks separate parts too; a / inside a word is text
        (
            "Read: https://example.com/a /info\n\n/dailypost ;/dailyquote",
            [
                Part("Read: https://example.com/a", "/info"),
                Part("", "/dailypost"),
                Part("", "/dailyquote"),
            ],
        ),
        # The file's texts are in marks, its spoilers' || too
        (
            "||Surprise!|| /ping; **Bins** \\*now\\*",
            [Part("||Surprise!||", "/ping"), Part("**Bins** \\*now\\*")],
        ),
    ],
)
def test_parts(text: str, parts: list[Part]) -> None:
    assert parse_parts(text, set()) == tuple(parts)


@pytest.mark.usefixtures("swedish")
def test_parts_keep_the_english_names() -> None:
    assert parse_parts("God morgon! /väder; /spådom startrek", set()) == (
        Part("God morgon!", "/weather"),
        Part("", "/fortune startrek"),
    )


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("", "What should it post?"),
        (" ; \n ", "What should it post?"),
        ("Hi /frobnicate", "/frobnicate isn't a command the bot knows."),
        ("/timer add 08:00 /ping", "Timers, specials and /run can't manage"),
        ("/specials", "Timers, specials and /run can't manage"),
        ("/msg 1 Hi", "Timers, specials and /run can't manage"),
        ("Hi | there /ping", "A special can't have a |"),
        ("Hi /Morning", "/Morning is a special of yours"),
        ("; ".join(["/ping"] * 6), "A special has at most 5 parts."),
    ],
)
def test_parts_refused(text: str, why: str) -> None:
    # As a message has them
    result = parse_parts(text, {"/morning"}, styles_of(text, None))
    assert isinstance(result, str)
    assert result.startswith(why)


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("/morning", None),
        ("/skämt", None),
        ("morning", "Give it a name"),
        ("/", "Give it a name"),
        ("/a|b", "Give it a name"),
        ("/weather", "/weather is a command already."),
        ("/test", "/test is a command already."),  # what /status has been
        ("/dailypost", "/dailypost is a command already."),
        ("/special", "/special is a command already."),
        ("/pic", "/pic is a command already."),  # an alias
    ],
)
def test_names(monkeypatch: pytest.MonkeyPatch, name: str, why: str | None) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic"]}')
    get_settings.cache_clear()
    result = check_name(name)
    if why is None:
        assert result is None
    else:
        assert (result or "").startswith(why)


async def test_add_list_change_and_remove(chat: Chat) -> None:
    [empty] = await chat.send("/specials")
    assert empty.startswith("No specials of your own yet.")
    assert await chat.send("/special add /morning Morning! /weather; /dailyquote") == [
        "✅ **Added /morning**\nMorning! /weather; /dailyquote"
    ]
    await chat.send("/special add /bins The bins go out tonight!")
    assert await chat.send("/specials") == [
        "**✨ 2 specials**\n"
        "**/bins** · The bins go out tonight!\n"
        "**/morning** · Morning! /weather; /dailyquote"
    ]
    # Changed, by its name in any case
    assert await chat.send("/special add /MORNING /weather") == [
        "✅ **Changed /morning**\n/weather"
    ]
    assert await chat.send("/special remove bins") == [
        "🗑️ **Removed /bins**\nThe bins go out tonight!"
    ]
    # Kept by their English names, privately
    path = get_settings().specials_file
    assert path.read_text().splitlines() == [*HEADER, "/morning | /weather"]
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/special frobnicate", "/specials: commands of your own"),
        ("/special add", "Give it a name"),
        ("/special add /weather Hi", "/weather is a command already."),
        ("/special add /morning", "What should it post?"),
        ("/special add /morning Hi /frobnicate", "/frobnicate isn't a command"),
        ("/special remove", "Which special?"),
        ("/special remove /nope", "There's no special /nope."),
    ],
)
async def test_refused(chat: Chat, text: str, answer: str) -> None:
    [reply] = await chat.send(text)
    assert reply.startswith(answer)
    assert not get_settings().specials_file.exists()


async def test_at_most_so_many(chat: Chat, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(specials, "MAX_SPECIALS", 1)
    await chat.send("/special add /a Hi")
    [refused] = await chat.send("/special add /b Hi")
    assert refused.startswith("There are 1 specials already")
    # But they can be changed
    [changed] = await chat.send("/special add /a Ho")
    assert changed.startswith("✅ **Changed /a**")


async def test_a_special_posts_its_parts_in_order(chat: Chat) -> None:
    await chat.send("/special add /morning Morning! /status; Hi; /ping")
    # The text heads the first answer of its command, or stands alone
    assert await chat.send("/morning") == [
        "Morning!\n\nchecks",
        "details",
        "Hi",
        "/ping!",
    ]
    assert chat.ran == ["/status", "/ping"]


async def test_an_edit_runs_or_changes_none_of_the_admins_own(chat: Chat) -> None:
    # Their commands may change something
    await chat.send("/special add /morning /ping")
    assert await chat.send("/morning", edit=True) == []
    assert await chat.send("/special add /bins Bins!", edit=True) == []
    assert chat.ran == []
    assert list(own_specials.current().specials) == ["/morning"]


def test_a_heading_is_in_marks() -> None:
    styled = SendMessage(text="**Help**", text_mode=TextMode.STYLED)
    assert headed("*Hi*", styled) == SendMessage(
        text="*Hi*\n\n**Help**", text_mode=TextMode.STYLED
    )
    # A plain answer is styled, as it shows
    plain = SendMessage(text="5 * 3", base64_attachments=["aGVq"])
    assert headed("*Hi*", plain) == SendMessage(
        text="*Hi*\n\n5 \\* 3", base64_attachments=["aGVq"], text_mode=TextMode.STYLED
    )


async def test_formatting_given_in_signal_is_kept(chat: Chat) -> None:
    # Commands stay as they are, formatted or not
    text = "/special add /morning Good morning! /weather; 🗑️ Bins tonight /ping"
    assert await chat.send(
        text,
        ("Good morning!", "BOLD"),
        ("/weather", "ITALIC"),
        ("tonight /ping", "SPOILER"),
    ) == ["✅ **Added /morning**\n**Good morning!** /weather; 🗑️ Bins ||tonight|| /ping"]
    assert await chat.send("/morning") == [
        "**Good morning!**\n\n/weather!",
        "🗑️ Bins ||tonight||\n\n/ping!",
    ]
    assert {reply.text_mode for reply in chat.replies} == {TextMode.STYLED}
    lines = get_settings().specials_file.read_text().splitlines()
    assert (
        lines[-1] == "/morning | **Good morning!** /weather; 🗑️ Bins ||tonight|| /ping"
    )
    # As the file has them, which is how they show
    assert await chat.send("/specials") == [
        "**✨ 1 special**\n"
        "**/morning** · **Good morning!** /weather; 🗑️ Bins ||tonight|| /ping"
    ]


async def test_typed_marks_show_as_typed(chat: Chat) -> None:
    await chat.send("/special add /sum 5 * 3 = 15 ~ish, see `x`")
    assert await chat.send("/sum") == ["5 \\* 3 = 15 \\~ish, see \\`x\\`"]
    assert chat.replies[0].text_mode == TextMode.STYLED


async def test_formatting_marks_can_t_say_is_refused(chat: Chat) -> None:
    # **Hel***lo* would read otherwise
    [reply] = await chat.send(
        "/special add /hi Hello", ("Hel", "BOLD"), ("lo", "ITALIC")
    )
    assert reply.startswith("That formatting can't be kept")
    assert not get_settings().specials_file.exists()


@pytest.mark.parametrize("alias", ["/s", "/specialkommando"])
async def test_formatting_after_an_alias(
    chat: Chat, monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    # The alias is replaced by /special, shorter or longer than it, and the
    # formatting moves with the rest of the text
    monkeypatch.setenv("NEJOMIBOT_ALIASES", f'{{"/special": ["{alias}"]}}')
    get_settings.cache_clear()
    assert await chat.send(f"{alias} add /hi Hi there!", ("there", "BOLD")) == [
        "✅ **Added /hi**\nHi **there**!"
    ]


async def test_the_admins_own_are_commands(chat: Chat) -> None:
    await chat.send("/special add /morning /ping")
    morning = known("/Morning")
    assert morning is not None and morning.timers
    assert check_commands(["/morning"]) is None
    assert known("/morning now") is None


async def test_a_special_a_timer_runs_isn_t_removed(chat: Chat) -> None:
    await chat.send("/special add /morning /ping")
    chat.keeper.add("daily 08:00", [ALICE], ["/morning"])
    chat.keeper.add("daily 09:00", [ALICE], ["/weather", "/Morning"])
    assert await chat.send("/special remove /morning") == [
        "Timers #1, #2 run it: remove those first, or change the special."
    ]
    assert list(own_specials.current().specials) == ["/morning"]


async def test_lines_it_can_t_read_are_left_as_they_are(
    chat: Chat, caplog: pytest.LogCaptureFixture
) -> None:
    get_settings().specials_file.write_text(
        "# Ours\n"
        "/bins | The bins!\n"
        "/weather | /ping\n"
        "/loop | /bins\n"
        "no bar\n"
        "/bins | Again!\n"
    )
    assert await chat.send("/specials") == [
        "**✨ 1 special**\n"
        "**/bins** · The bins!\n"
        "⚠️ The file has 4 lines the bot can't read, and leaves as they are: "
        "/weather \\| /ping / /loop \\| /bins / no bar / /bins \\| Again!"
    ]
    # By number: what a line says is the admins' text
    assert "Specials line 3 left alone" in caplog.text
    assert "is a command already" not in caplog.text
    # A new /bins takes the place of both
    await chat.send("/special add /bins New!")
    lines = get_settings().specials_file.read_text().splitlines()
    assert lines == [
        "# Ours",
        "/weather | /ping",
        "/loop | /bins",
        "no bar",
        "/bins | New!",
    ]
