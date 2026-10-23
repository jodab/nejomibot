from typing import cast

import pytest
from helpers import ALICE, BOB, GROUP, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import i18n, notices, weather
from nejomibot.config import get_settings
from nejomibot.help import Help
from nejomibot.i18n import ChatLanguage, _
from nejomibot.languages import Language


def allow(*people: str) -> None:
    get_settings().allowed_file.write_text("".join(f"{each}\n" for each in people))


def own(*lines: str) -> None:
    """Chats' own languages, as data_dir/languages.txt keeps them."""
    get_settings().data_file("languages.txt").write_text(
        "".join(f"{line}\n" for line in lines)
    )


async def send(
    text: str,
    *,
    sender: str = ALICE,
    bot: SignalBot | None = None,
    in_group: bool = False,
    handler: Language | Help | None = None,
) -> None:
    message = message_from(sender, text, in_group=in_group)
    context = DataMessageContext(cast(SignalBot, bot), message)
    await (handler or Language()).handle_data_message(context)


def texts(answers: list[SendMessage]) -> list[str]:
    return [answer.text or "" for answer in answers]


def entries() -> list[ChatLanguage]:
    return i18n.chat_languages.current().entries


# Greek's own name, as el.toml has it
GREEK = i18n.names_of("el").name
USAGE = (
    "/language <language>: the bot speaks it here, as /language el; /language "
    "default: its own again."
)


async def test_the_languages(answers: list[SendMessage]) -> None:
    allow(ALICE)
    await send("/language")
    assert texts(answers) == [
        f"🗣️ **Languages**\nEnglish (en) ✓ here\n{GREEK} (el)\nSvenska (sv)\n{USAGE}"
    ]


async def test_a_persons_own_language(answers: list[SendMessage]) -> None:
    allow(ALICE, BOB)
    await send("/language svenska")
    # Said in the language now spoken there
    assert texts(answers) == ["✅ Svenska (sv) här från och med nu."]
    assert entries() == [ChatLanguage(ALICE, "sv")]
    # The bot answers her in Swedish, Bob still in English; by the Swedish
    # name, which the bot takes from anyone
    await send("/språk")
    await send("/språk", sender=BOB)
    assert texts(answers)[1].startswith(
        f"🗣️ **Språk**\nEnglish (en)\n{GREEK} (el)\nSvenska (sv) ✓ här"
    )
    assert texts(answers)[2].startswith("🗣️ **Languages**\nEnglish (en) ✓ here")
    # The config's again: said in it
    await send("/språk standard")
    assert texts(answers)[3] == "✅ The bot's own language here again: English (en)."
    assert entries() == []


async def test_what_language_can_t_read(answers: list[SendMessage]) -> None:
    allow(ALICE)
    await send("/language klingon")
    await send("/language 2 sv")  # numbers: for the admins
    await send("/language two sv")
    assert texts(answers) == [
        f"The bot doesn't speak klingon: it speaks English (en), {GREEK} (el), "
        "Svenska (sv).",
        "Only the admins, in a direct chat, give chats of /chats a language.",
        USAGE,
    ]
    assert entries() == []


async def test_a_groups_language_is_an_admins_to_change(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{BOB}"]')
    get_settings.cache_clear()
    await send("/language sv", bot=bot, in_group=True)
    await send("/language sv", bot=bot, in_group=True, sender=BOB)
    assert texts(answers) == [
        "Only an admin can change the language of a group.",
        "✅ Svenska (sv) här från och med nu.",
    ]
    assert entries() == [ChatLanguage(GROUP, "sv")]
    # Everyone there gets Swedish now, but in a direct chat
    await send("/language", bot=bot, in_group=True)
    assert texts(answers)[2].startswith("🗣️ **Språk**")


async def test_an_admin_gives_chats_of_chats_a_language(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{BOB}"]')
    get_settings.cache_clear()
    allow(ALICE)
    # /chats: 1 the group, 2 Alice, 3 Bob
    await send("/language 2,1 sv", bot=bot, sender=BOB)
    # In the order given
    assert texts(answers)[0] == "✅ Svenska (sv) for Alice (+46700000001), Familjen."
    assert entries() == [ChatLanguage(ALICE, "sv"), ChatLanguage(GROUP, "sv")]
    # The admin sees them with theirs
    await send("/language", bot=bot, sender=BOB)
    assert (
        "Chats with a language of their own:\n1 👥 Familjen: Svenska (sv)\n2 👤 "
        in (texts(answers)[1] or "")
    )
    await send("/language 1 default", bot=bot, sender=BOB)
    assert entries() == [ChatLanguage(ALICE, "sv")]


async def test_an_edit_takes_the_place_of_a_language(
    answers: list[SendMessage],
) -> None:
    allow(ALICE)
    await send("/language sv")
    edit = message_from(ALICE, "/language en", edit=True)
    await Language().handle_data_message(
        DataMessageContext(cast(SignalBot, None), edit)
    )
    assert entries() == [ChatLanguage(ALICE, "en")]
    assert texts(answers)[-1] == "✅ English (en) here from now on."


async def test_commands_answer_in_the_chats_language(
    answers: list[SendMessage],
) -> None:
    allow(ALICE, BOB)
    own(f"{ALICE} | sv")
    await send("/help", handler=Help())
    await send("/help", sender=BOB, handler=Help())
    swedish, english = texts(answers)
    assert swedish.startswith("**Kommandon**\n📷 `/bild [<album>]`")
    assert swedish.endswith("Alla kommandon fungerar också med sina engelska namn.")
    assert english.startswith("**Commands**\n📷 `/photo [<album>]`")


def test_a_line_it_can_t_read_is_left_alone() -> None:
    own(f"{ALICE} | sv", f"{BOB} | klingon", "no language")
    assert entries() == [ChatLanguage(ALICE, "sv")]
    assert len(i18n.chat_languages.broken) == 2
    assert i18n.chat_language(BOB) == "en"


def test_chats_by_language() -> None:
    own(f"{GROUP} | sv")
    assert i18n.by_language([ALICE, GROUP, BOB]) == {"en": [ALICE, BOB], "sv": [GROUP]}


def test_no_name_means_two_things() -> None:
    commands: dict[str, str] = {}
    words: dict[str, str] = {}
    for language in i18n.every_language():
        for command, names in language.commands.items():
            for name in names:
                assert commands.setdefault(name.casefold(), command) == command, name
        for word, phrases in language.words.items():
            for phrase in phrases:
                assert words.setdefault(phrase.casefold(), word) == word, phrase


async def test_each_admin_hears_in_their_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ALICE}", "{BOB}"]')
    get_settings.cache_clear()
    own(f"{BOB} | sv")
    sent: list[tuple[str, str | None]] = []

    async def send(_bot: SignalBot, recipient: str, message: SendMessage) -> None:
        sent.append((recipient, message.text))

    monkeypatch.setattr(notices, "send", send)
    worded = await notices.worded(lambda: _("Languages"))
    assert worded == {"en": "Languages", "sv": "Språk"}
    await notices.tell(cast(SignalBot, None), worded)
    assert sent == [(ALICE, "Languages"), (BOB, "Språk")]


def test_a_place_is_named_in_the_language_spoken() -> None:
    place = weather.Place("57.7", "11.97", "Gothenburg", ("SE",), {"sv": "Göteborg"})
    assert place.name == "Gothenburg, SE"
    with i18n.speaking("sv"):
        assert place.name == "Göteborg, SE"
