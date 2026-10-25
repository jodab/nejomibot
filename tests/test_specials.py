from typing import Any, cast

import pytest
from helpers import ALICE, GROUP, message_from, text_styles
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import commands, receipts, specials
from nejomibot.commands import Command, aliases, canonical, known
from nejomibot.config import get_settings
from nejomibot.messages import PerChat, for_chat
from nejomibot.specials import (
    HEADER,
    Part,
    Special,
    Specials,
    SpecialsForEveryone,
    check_name,
    joined,
    own_specials,
    parse_line,
    parse_parts,
)
from nejomibot.styles import styles_of, unmarked
from nejomibot.timers import Timekeeper, check_commands

ADMIN = "+46700000009"


class Groups:
    """As the bot's groups resolve a group's: to GROUP."""

    def resolve(self, group: str) -> str:
        return GROUP


class Bot:
    groups = Groups()


class Chat:
    """An admin's direct chat with the bot: what it answers there, and the
    commands the specials run, which answer as below."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.replies: list[SendMessage] = []
        self.ran: list[str] = []
        self.ran_as: list[str | None] = []  # whose message each ran as
        self.ran_in_group: list[bool] = []  # and whether as in a group
        self.keeper = Timekeeper()
        monkeypatch.setattr(commands, "reply", self.reply)
        monkeypatch.setattr(commands, "mark_read", self.nothing)
        monkeypatch.setattr(receipts, "show_typing", self.nothing)
        monkeypatch.setattr(receipts, "stop_typing", self.nothing)
        monkeypatch.setattr(self.keeper, "answers_to", self.answers_to)
        monkeypatch.setattr(specials, "timekeeper", self.keeper)

    async def reply(self, context: DataMessageContext, message: SendMessage) -> None:
        self.replies.append(message)

    async def nothing(self, context: DataMessageContext) -> None:
        pass

    async def answers_to(
        self, command: str, admin: DataMessage | None = None
    ) -> list[SendMessage]:
        """Two answers to /status, as it has; none to /today, as on a day
        with nothing special; one to the rest."""
        self.ran.append(command)
        self.ran_as.append(admin.source_number if admin else None)
        self.ran_in_group.append(bool(admin and admin.is_group()))
        if command == "/status":
            return [SendMessage(text="checks"), SendMessage(text="details")]
        if command == "/today":
            return []
        return [SendMessage(text=f"{command}!")]

    async def send_as(self, sender: str, text: str) -> list[str]:
        """What the bot answers someone allowed who sends the text in a
        group, as everyone allowed's specials have it."""
        message = message_from(sender, text, in_group=True)
        self.replies.clear()
        await SpecialsForEveryone().handle_data_message(
            DataMessageContext(cast(SignalBot, Bot()), message)
        )
        return [reply.text or "" for reply in self.replies]

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
        # An edit is of the message before, as Signal names it
        if edit:
            fields["timestamp"] = 3
        message = (
            EditMessage(**fields, target_sent_timestamp=2)
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
            "Read: https://example.com/a /info\n\n/today ;/uniquephoto",
            [
                Part("Read: https://example.com/a", "/info"),
                Part("", "/today"),
                Part("", "/uniquephoto"),
            ],
        ),
        # The file's texts are in marks, its spoilers' || too
        (
            "||Surprise!|| /ping; **Bins** \\*now\\*",
            [Part("||Surprise!||", "/ping"), Part("**Bins** \\*now\\*")],
        ),
        # A + of its own joins a part to the one before, in its message
        (
            "/today + /weather; Photo! /uniquephoto",
            [
                Part("", "/today"),
                Part("", "/weather", joined=True),
                Part("Photo!", "/uniquephoto"),
            ],
        ),
        # Text too, and across a line break
        (
            "/today\n+ /weather +\nBye!",
            [
                Part("", "/today"),
                Part("", "/weather", joined=True),
                Part("Bye!", joined=True),
            ],
        ),
        # A + in a word is text, and one before the first part joins nothing
        (
            "+ C++ /ping; +4670000000 /info",
            [Part("C++", "/ping"), Part("+4670000000", "/info")],
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
        ("/timer add 08:00 /ping", "Timers, specials and /run can't run /timer."),
        ("/specials add /x Hi", "Timers, specials and /run can't run /specials."),
        ("/msg 1 Hi", "Timers, specials and /run can't run /msg."),
        ("Hi /Morning", "/Morning is a special of yours"),
        ("; ".join(["/ping"] * 6), "A special has at most 5 parts."),
        (" + ".join(["/ping"] * 6), "A special has at most 5 parts."),
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
        ("/today", "/today is a command already."),
        ("/dailypost", None),  # a command the bot had once
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
    assert await chat.send("/special add /morning Morning! /weather; /fortune") == [
        "✅ **Added /morning**\nMorning! /weather; /fortune"
    ]
    await chat.send("/special add /bins The bins go out tonight!")
    assert await chat.send("/specials") == [
        "**✨ 2 specials**\n"
        "**/bins** · The bins go out tonight!\n"
        "**/morning** · Morning! /weather; /fortune"
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
    # As the admin who ran it, as /run runs commands
    assert chat.ran_as == [ADMIN, ADMIN]


async def test_parts_joined_by_a_plus_post_in_one_message(chat: Chat) -> None:
    await chat.send("/special add /morning Morning! /status + /ping; Hi + Bye; /ping")
    # All that they post, both answers of /status too, and nothing more for
    # one that answers nothing
    assert await chat.send("/morning") == [
        "Morning!\n\nchecks\n\ndetails\n\n/ping!",
        "Hi\n\nBye",
        "/ping!",
    ]
    await chat.send("/special add /daily /today + /weather")
    assert await chat.send("/daily") == ["/weather!"]
    # Kept and shown as given
    lines = get_settings().specials_file.read_text().splitlines()
    assert lines[-2:] == [
        "/morning | Morning! /status + /ping; Hi + Bye; /ping",
        "/daily | /today + /weather",
    ]
    assert await chat.send("/specials") == [
        "**✨ 2 specials**\n"
        "**/daily** · /today + /weather\n"
        "**/morning** · Morning! /status + /ping; Hi + Bye; /ping"
    ]


async def test_shortcuts_are_other_names_for_a_special(chat: Chat) -> None:
    await chat.send("/special add /morning /ping")
    assert await chat.send("/special shortcuts /morning /gm /good") == [
        "✅ Shortcuts for /morning: /gm, /good."
    ]
    # Taken as its name is, in any case
    assert await chat.send("/GM") == ["/ping!"]
    assert await chat.send("/good") == ["/ping!"]
    assert check_commands(["/gm"]) is None
    assert canonical("/gm") == "/morning"
    # Kept with it, also when it changes, and listed with it
    await chat.send("/special add /morning /weather")
    lines = get_settings().specials_file.read_text().splitlines()
    assert lines[-1] == "/morning /gm /good | /weather"
    assert await chat.send("/specials") == [
        "**✨ 1 special**\n**/morning** · /weather · 🏷️ /gm /good"
    ]
    # Taken away
    assert await chat.send("/special shortcuts /morning -") == [
        "✅ /morning: no shortcuts."
    ]
    assert await chat.send("/special shortcuts /morning -") == [
        "/morning has no shortcuts."
    ]
    assert "/gm" not in aliases()
    assert get_settings().specials_file.read_text().splitlines()[-1] == (
        "/morning | /weather"
    )


async def test_names_parts_and_shortcuts_with_a_dot(
    chat: Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Shown with a ., unless command_prefix is a /; the file keeps the /
    monkeypatch.setenv("NEJOMIBOT_COMMAND_PREFIX", ".")
    get_settings.cache_clear()
    assert await chat.send(".special add .morning Hi! .ping + .info") == [
        "✅ **Added .morning**\nHi! .ping + .info"
    ]
    assert await chat.send(".special shortcuts .morning .gm") == [
        "✅ Shortcuts for .morning: .gm."
    ]
    lines = get_settings().specials_file.read_text().splitlines()
    assert lines[-1] == "/morning /gm | Hi! /ping + /info"
    assert await chat.send(".GM") == ["Hi!\n\n/ping!\n\n/info!"]
    assert await chat.send("/specials") == [
        "**✨ 1 special**\n**.morning** · Hi! .ping + .info · 🏷️ .gm"
    ]
    assert await chat.send(".special remove .morning") == [
        "🗑️ **Removed .morning**\nHi! .ping + .info"
    ]


async def test_a_shortcut_cant_hide_a_name(
    chat: Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic"]}')
    get_settings.cache_clear()
    get_settings().data_file("albums.txt").write_text("Alice | | /alice\n")
    await chat.send("/special add /bins Bins!")
    await chat.send("/special shortcuts /bins /b")
    await chat.send("/special add /morning /ping")
    answers = [
        (await chat.send(text))[0]
        for text in (
            "/special shortcuts",
            "/special shortcuts /nope /n",
            "/special shortcuts /morning /weather",
            "/special shortcuts /morning /väder",  # Swedish for /weather
            "/special shortcuts /morning /test",  # the bot's own alias
            "/special shortcuts /morning /bins",
            "/special shortcuts /morning /morning",
            "/special shortcuts /morning /pic",
            "/special shortcuts /morning /B",
            "/special shortcuts /morning /Alice",
            "/special shortcuts /morning a|b",
            "/special shortcuts /morning a b c d e f",
        )
    ]
    assert answers == [
        "Which special? Give its name, as /specials shows.",
        "There's no special /nope.",
        "/weather is a command already.",
        "/väder is a command already.",
        "/test is a command already.",
        "/bins is a command already.",
        "/morning is a command already.",
        "/pic is an alias in the config: take it out there first.",
        "/B is a shortcut for /bins already.",
        "/Alice is a shortcut for /photo Alice already.",
        "A shortcut can't have a \\| or a ;.",  # escaped, as the answer is styled
        "A special has at most 5 shortcuts.",
    ]
    assert own_specials.current().shortcuts == {"/bins": ("/b",)}
    # Nor can a special, or an album, take a shortcut's name
    assert await chat.send("/special add /b Hi!") == ["/b is a command already."]


async def test_shortcuts_go_and_come_back_with_their_special(chat: Chat) -> None:
    await chat.send("/special add /bins Bins!")
    await chat.send("/special shortcuts /bins /b")
    await chat.send("/special add /morning /ping")
    await chat.send("/special remove /bins")
    assert "/b" not in aliases()
    # An edit of the removal undoes it, then removes the special it names
    await chat.send("/special remove /morning", edit=True)
    assert own_specials.current().shortcuts == {"/bins": ("/b",)}
    assert aliases()["/b"] == "/bins"
    # An edit of shortcuts takes the place of those it set
    await chat.send("/special shortcuts /bins /c")
    await chat.send("/special shortcuts /bins /d", edit=True)
    assert own_specials.current().shortcuts == {"/bins": ("/d",)}
    assert "/c" not in aliases()


@pytest.mark.usefixtures("swedish")
async def test_shortcuts_in_swedish(chat: Chat) -> None:
    await chat.send("/special lägg till /morgon /ping")
    assert await chat.send("/special genvägar /morgon /gm") == [
        "✅ Genvägar för /morgon: /gm."
    ]
    assert await chat.send("/gm") == ["/ping!"]


@pytest.mark.parametrize(
    "lines",
    [
        # A shortcut that is a command, or another special's name, would hide it
        ["/morning /weather | /ping"],
        ["/morning /bins | /ping", "/bins | Bins!"],
    ],
)
def test_a_line_whose_shortcut_hides_a_name_isnt_read(lines: list[str]) -> None:
    get_settings().specials_file.write_text("\n".join(lines) + "\n")
    found = own_specials.current()
    assert found.broken == [lines[0]]
    assert "/morning" not in found.specials
    assert found.shortcuts == {}


async def test_an_edit_runs_a_special_again_or_changes_it(chat: Chat) -> None:
    await chat.send("/special add /morning /ping")
    # One of the admins' own runs again: its commands change nothing
    assert await chat.send("/morning", edit=True) == ["/ping!"]
    # An edit of a change takes the place of what it edits
    await chat.send("/special add /bins Bins!")
    await chat.send("/special add /bins Bins tonight!", edit=True)
    assert own_specials.current().specials["/bins"] == (Part("Bins tonight!"),)
    await chat.send("/special add /morning /weather")
    await chat.send("/special add /morning /fortune", edit=True)
    assert own_specials.current().specials["/morning"] == (Part("", "/fortune"),)
    await chat.send("/special remove /bins")
    await chat.send("/special remove /morning", edit=True)
    assert list(own_specials.current().specials) == ["/bins"]


def test_messages_joined_are_styled_if_one_is() -> None:
    heading = SendMessage(text="*Hi*", text_mode=TextMode.STYLED)
    styled = SendMessage(text="**Help**", text_mode=TextMode.STYLED)
    assert joined([heading, styled]) == SendMessage(
        text="*Hi*\n\n**Help**", text_mode=TextMode.STYLED
    )
    # A plain one is escaped, as it shows, and the photos are all kept
    plain = SendMessage(text="5 * 3", base64_attachments=["aGVq"])
    photo = SendMessage(base64_attachments=["ZGVq"], text_mode=TextMode.STYLED)
    assert joined([heading, plain, photo]) == SendMessage(
        text="*Hi*\n\n5 \\* 3",
        base64_attachments=["aGVq", "ZGVq"],
        text_mode=TextMode.STYLED,
    )
    # Plain ones stay plain
    assert joined([plain, SendMessage(text="Hi")]) == SendMessage(
        text="5 * 3\n\nHi", base64_attachments=["aGVq"]
    )


def test_each_chat_s_own_text_is_joined_too() -> None:
    # As /today's, with birthdays in a group and nothing elsewhere
    day = PerChat(
        text="", texts={GROUP: "🎂 Alice turns 36 today!"}, text_mode=TextMode.STYLED
    )
    weather = SendMessage(text="**Weather**", text_mode=TextMode.STYLED)
    post = joined(
        [SendMessage(text="**Hi!**", text_mode=TextMode.STYLED), day, weather]
    )
    assert for_chat(post, GROUP).text == (
        "**Hi!**\n\n🎂 Alice turns 36 today!\n\n**Weather**"
    )
    assert for_chat(post, ALICE).text == "**Hi!**\n\n**Weather**"


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
    await chat.send("/special add /sum 5 * 3 = 15 ~ish, see `x` | y || z")
    shown = "5 \\* 3 = 15 \\~ish, see \\`x\\` \\| y \\|\\| z"
    assert await chat.send("/sum") == [shown]
    assert chat.replies[0].text_mode == TextMode.STYLED
    # Only the first | separates the name, as the file is read again
    line = get_settings().specials_file.read_text().splitlines()[-1]
    assert line == f"/sum | {shown}"
    assert parse_line(line, set())[1] == (Part(shown, ""),)
    assert unmarked(shown)[0] == "5 * 3 = 15 ~ish, see `x` | y || z"


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


@pytest.mark.usefixtures("swedish")
async def test_formatting_after_a_subcommand(chat: Chat) -> None:
    # lägg till is replaced by add, shorter than it, and the formatting moves
    # with the rest of the text
    assert await chat.send("/special lägg till /hej Hej på er!", ("på er", "BOLD")) == [
        "✅ **La till /hej**\nHej **på er**!"
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
        "⚠️ The file has 4 unreadable lines, which are ignored and left "
        "unchanged: /weather \\| /ping / /loop \\| /bins / no bar / /bins \\| Again!"
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


async def test_a_plain_word_shortcut_is_taken_with_a_slash(chat: Chat) -> None:
    await chat.send("/special add /morning /ping")
    # A plain word would make every message that starts with it a command
    assert await chat.send("/special shortcuts /morning gm") == [
        "✅ Shortcuts for /morning: /gm."
    ]
    assert await chat.send("gm, everyone!") == []
    assert await chat.send(".gm") == ["/ping!"]
    # One in the file from before is read with its / too
    get_settings().specials_file.write_text("/evening ge /ge | /ping\n")
    assert own_specials.current().shortcuts == {"/evening": ("/ge",)}
    assert canonical("ge") == "ge"
    assert canonical("/ge") == "/evening"


# Specials for everyone allowed


async def test_one_for_everyone(chat: Chat) -> None:
    await chat.send("/special add /morning Good morning! /weather; /today")
    assert await chat.send("/special everyone /morning") == [
        "✅ Everyone allowed may use /morning now, in groups too, and /help lists it."
    ]
    lines = get_settings().specials_file.read_text().splitlines()
    assert lines[-1] == "/morning (everyone) | Good morning! /weather; /today"
    # Still so as it changes, or gets shortcuts
    await chat.send("/special add /morning Hi! /weather")
    await chat.send("/special shortcuts /morning /gm")
    lines = get_settings().specials_file.read_text().splitlines()
    assert lines[-1] == "/morning /gm (everyone) | Hi! /weather"
    assert await chat.send("/specials") == [
        "**✨ 1 special**\n**/morning** · Hi! /weather · 🏷️ /gm · 👥 for everyone"
    ]
    # Taken by the everyday commands' handler, not the admins'
    assert Specials.takes("/morning") is None
    assert SpecialsForEveryone.takes("/Morning") == Command("/morning")
    assert await chat.send("/special everyone /morning") == [
        "Everyone allowed may use /morning already."
    ]
    assert await chat.send("/special admins morning") == [
        "✅ Only the admins may use /morning now."
    ]
    assert await chat.send("/special admins /morning") == [
        "Only the admins may use /morning already."
    ]
    assert get_settings().specials_file.read_text().splitlines()[-1] == (
        "/morning /gm | Hi! /weather"
    )
    assert SpecialsForEveryone.takes("/morning") is None


async def test_one_for_everyone_runs_as_whoever_sends_it(chat: Chat) -> None:
    await chat.send("/special add /morning Morning! /weather + /ping")
    await chat.send("/special everyone /morning")
    # Alice, who isn't an admin, in a group: its commands run as hers, there
    assert await chat.send_as(ALICE, "/morning") == ["Morning!\n\n/weather!\n\n/ping!"]
    assert chat.ran_as[-2:] == [ALICE, ALICE]
    assert chat.ran_in_group[-2:] == [True, True]


async def test_admin_commands_in_one_for_everyone_are_named(chat: Chat) -> None:
    await chat.send("/special add /peek /status; /contacts 3; /weather")
    assert await chat.send("/special everyone /peek") == [
        "✅ Everyone allowed may use /peek now, in groups too, and /help lists it.\n"
        "⚠️ It runs admin commands: /status, /contacts. Everyone allowed who uses "
        "it, in a group too, now sees what they show, and has them do what they "
        "do; /special admins /peek takes that back."
    ]
    # And as it changes
    [changed] = await chat.send("/special add /peek /today preview; /weather")
    assert changed.endswith(
        "\n⚠️ It runs admin commands: /today preview. "
        "Everyone allowed who uses it, in a group too, now sees what they show, "
        "and has them do what they do; /special admins /peek takes that back."
    )
    # Not for one of everyday commands, nor once it's for the admins alone
    await chat.send("/special add /peek /weather")
    [plain] = await chat.send("/special add /peek /weather")
    assert "⚠️" not in plain
    await chat.send("/special admins /peek")
    [alone] = await chat.send("/special add /peek /status")
    assert "⚠️" not in alone


async def test_an_edit_takes_the_place_of_who_may_use_one(chat: Chat) -> None:
    await chat.send("/special add /morning /ping")
    await chat.send("/special add /bins Bins!")
    await chat.send("/special everyone /morning")
    await chat.send("/special everyone /bins", edit=True)
    assert own_specials.current().everyone == {"/bins"}
    # A removal undone puts it back for everyone, as it was
    await chat.send("/special remove /bins")
    await chat.send("/special remove /nope", edit=True)
    assert own_specials.current().everyone == {"/bins"}


def test_a_line_for_everyone_reads_back() -> None:
    line = "/morning /gm (Everyone) | Hi! /weather"
    assert parse_line(line, set()) == Special(
        "/morning", (Part("Hi!", "/weather"),), ("/gm",), everyone=True
    )
    # Wherever it is among the names
    assert parse_line("(everyone) /morning | /ping", set()).everyone
    assert not parse_line("/morning | /ping", set()).everyone


@pytest.mark.usefixtures("swedish")
async def test_one_for_everyone_in_swedish(chat: Chat) -> None:
    await chat.send("/special lägg till /morgon /ping")
    assert await chat.send("/special för alla /morgon") == [
        "✅ Alla tillåtna får använda /morgon nu, även i grupper, och /hjälp "
        "listar det."
    ]
    assert await chat.send("/special för admins /morgon") == [
        "✅ Bara admins får använda /morgon nu."
    ]
