import re
from pathlib import Path
from typing import cast

import pytest
from helpers import ALICE, make_jpeg, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import access
from nejomibot.bot import handlers
from nejomibot.config import get_settings
from nejomibot.help import ADMIN, ENTRIES, EVERYDAY, HELP, Help, help_for, help_message
from nejomibot.i18n import COMMAND_SLASH, languages, speaking
from nejomibot.photos import AlbumSettings, album_settings
from nejomibot.styles import unmarked


def commands(*, everyday: bool) -> set[str]:
    """The commands of the handlers for everyone allowed, or for the admins."""
    return {
        command.name
        for handler, _contacts, _groups, check in handlers(
            cast(SignalBot, None), get_settings()
        )
        if (check is not access.from_admin) == everyday
        for command in handler.commands
    }


def names(*, everyday: bool) -> set[str]:
    """Their names, without the words after them: /today for /today preview."""
    return {name.split()[0] for name in commands(everyday=everyday)}


def test_help_has_every_command_in_its_place() -> None:
    # A line for each everyday command but /help, which ends the list; and a
    # name for each admin command, but those of everyday ones, as /today
    # preview, which their pages have
    everyday = {entry.name for group in EVERYDAY for entry in group}
    assert everyday | {HELP.name} == names(everyday=True)
    admin = {entry.name for group in ADMIN for entry in group}
    assert admin == names(everyday=False) - names(everyday=True)


def test_every_command_has_its_page() -> None:
    for name in commands(everyday=True) | commands(everyday=False):
        entry = ENTRIES[name.split()[0]]
        assert entry.what and entry.page, name
        if " " in name:  # as /contacts add, on the page of /contacts
            assert name in entry.page + entry.admins, name


def test_the_readme_has_every_command() -> None:
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    for command in commands(everyday=True) | commands(everyday=False):
        assert f"| `{command}" in readme, command


def listed(command: str, text: str) -> bool:
    return bool(re.search(rf"`{re.escape(command)}[ `]", text))


def test_admins_see_every_command() -> None:
    text = help_message(admin=True)
    for name in names(everyday=True) | names(everyday=False):
        assert listed(name, text), name


def test_others_see_the_everyday_commands() -> None:
    text = help_message(admin=False)
    for name in names(everyday=True):
        assert listed(name, text), name
    for name in names(everyday=False) - names(everyday=True):
        assert not listed(name, text), name


def test_a_short_line_per_command() -> None:
    # What each does, without what may follow it, in groups; then how to see
    # more, with a command of the bot's own as the example
    text = help_message(admin=False)
    assert text.startswith(
        "**Commands**\n"
        "📷 `/photo` – a random photo\n"
        "🆕 `/uniquephoto` – a photo not sent yet\n"
        "🏞️ `/sphoto` – a photo without its caption\n"
    )
    # /day, which /today was before, is one of its names
    assert "\n\n🌅 `/today` – the date, holidays and birthdays (/day)\n" in text
    assert text.endswith(
        "🏓 `/ping` – is the bot there?\n\n"
        "Send `/help` and a command for more about it, as `/help photo`."
    )


def test_the_admin_commands_by_name() -> None:
    text = help_message(admin=True)
    assert text.startswith("**For everyone allowed**\n📷 `/photo` – a random photo\n")
    assert (
        "\n\n**Admins, in a direct chat**\n"
        "🩺 `/status` `/delivery` `/incoming` `/delete` `/mention`\n"
        "📋 `/allowed` `/allow` `/disallow` `/admins` `/admin`\n"
    ) in text
    assert "🪪 `/profile` `/name` `/about` `/avatar` `/username`\n\nSend" in text


def test_a_page() -> None:
    # The command's line, then examples, in monospace, and what they do
    assert help_for("list", admin=False).splitlines() == [
        "📝 `/list` – this chat's list",
        "A shared list, such as for shopping.",
        "`/list` – the list, numbered",
        "`/list add milk, eggs` – add things, separated by commas",
        "`/list remove 2,5` – take numbers 2 and 5 off",
        "`/list clear` – take everything off",
    ]


def test_a_page_as_the_bot_is_set_up() -> None:
    page = help_for("weather", admin=False)
    assert "`/weather` – in Stockholm\n" in page
    assert "in Stockholm time" in help_for("remind", admin=False)


def test_by_any_of_its_names(monkeypatch: pytest.MonkeyPatch) -> None:
    # Its . or / or none, in any case, an alias, or a language's name for it
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic"]}')
    get_settings.cache_clear()
    page = help_for("photo", admin=False)
    assert page.startswith("📷 `/photo` – a random photo (/pic)\n")
    for name in ("/photo", ".photo", "Photo", "pic", ".pic", "/bild", "bild"):
        assert help_for(name, admin=False) == page, name


def test_more_for_the_admins_on_some_pages() -> None:
    assert "preview" not in help_for("today", admin=False)
    assert "\n`/today preview` – what /today says in each chat\n" in help_for(
        "today", admin=True
    )


def test_admin_commands_only_for_the_admins() -> None:
    assert help_for("status", admin=False) == (
        "There's no command /status here. /help lists those you can use."
    )
    assert help_for("status", admin=True).startswith(
        "🩺 `/status` – how the bot and the server are (/test)\n"
    )
    assert help_for("nothing", admin=True) == (
        "There's no command /nothing here. /help lists those you can use."
    )


def test_its_own_page() -> None:
    assert help_for("help", admin=False).splitlines() == [
        "❓ `/help` – the commands you can use",
        "`/help photo` – more about /photo, and so on for every command",
        "Commands start with . or /, whichever is easier to type.",
    ]


def test_an_albums_shortcut(photos_dir: Path) -> None:
    # What it stands for, then the page of /photo
    (photos_dir / "Alice").mkdir()
    make_jpeg(photos_dir / "Alice" / "a.jpg")
    album_settings.add(AlbumSettings("Alice", None, ("/alice",)))
    page = help_for(".alice", admin=False).splitlines()
    assert page[:2] == [
        "`/alice` is short for `/photo Alice`.",
        "📷 `/photo` – a random photo",
    ]


def test_a_special() -> None:
    get_settings().specials_file.write_text(
        "/morning /gm (everyone) | **Good morning!** /today + /weather; /uniquephoto\n"
        "/bins | Bins!\n"
    )
    page = (
        "✨ `/morning` – Good morning! /today + /weather; /uniquephoto (/gm)\n"
        "An admin's own command: it posts these, in order."
    )
    for name in ("morning", "/gm"):
        assert help_for(name, admin=False) == page, name
    # The admins' own, for them alone
    assert help_for("bins", admin=False).startswith("There's no command /bins here.")
    assert help_for("bins", admin=True).startswith("✨ `/bins` – Bins!\n")


async def test_the_command(answers: list[SendMessage]) -> None:
    # The first word after it, in any language
    for text in ("/help", "/help  .photo 2017", "/hjälp bild"):
        message = message_from(ALICE, text)
        await Help().handle_data_message(
            DataMessageContext(cast(SignalBot, None), message)
        )
    overview, photo, in_swedish = (answer.text for answer in answers)
    assert overview == help_message(admin=False)
    assert photo == in_swedish == help_for("photo", admin=False)


def test_the_specials_for_everyone_are_listed() -> None:
    get_settings().specials_file.write_text(
        "/morning /gm (everyone) | **Good morning!** /today + /weather; /uniquephoto\n"
        "/bins | Bins!\n"
    )
    line = "✨ `/morning` – Good morning! /today + /weather; /uniquephoto (/gm)"
    for admin in (False, True):
        text = help_message(admin=admin)
        assert f"**Specials**\n{line}\n" in text
        assert "/bins" not in text


def test_aliases_are_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A plain word with a /, and each once
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic", "snap", "PIC"]}')
    get_settings.cache_clear()
    text = help_message(admin=False)
    assert "📷 `/photo` – a random photo (/pic, /snap)\n" in text


def test_an_alias_is_listed_by_the_command_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The config's, before the bot's own
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/test"], "/status": ["/s"]}')
    get_settings.cache_clear()
    assert "📷 `/photo` – a random photo (/test)\n" in help_message(admin=True)
    assert help_for("status", admin=True).startswith(
        "🩺 `/status` – how the bot and the server are (/s)\n"
    )
    assert help_for("test", admin=True).startswith("📷 `/photo`")


def test_commands_show_with_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    # A ., unless command_prefix is a /: in the lines, the aliases, the pages
    monkeypatch.setenv("NEJOMIBOT_COMMAND_PREFIX", ".")
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic", "snap"]}')
    get_settings.cache_clear()
    text = help_message(admin=True)
    assert "📷 `.photo` – a random photo (.pic, .snap)\n" in text
    assert text.endswith(
        "Send `.help` and a command for more about it, as `.help photo`."
    )
    assert not COMMAND_SLASH.search(text)
    page = help_for("/timer", admin=True)
    assert "\n`.timer add 08:00 1,2 .today` – every day at 08:00, to chats 1" in page
    assert not COMMAND_SLASH.search(page)


@pytest.mark.usefixtures("swedish")
def test_in_swedish() -> None:
    text = help_message(admin=True)
    # By their Swedish names, which they have
    assert "🌤️ `/väder` – vädret just nu\n" in text
    assert "👥 `/kontakter` `/verifiera`\n" in text
    assert text.endswith(
        "Skicka `/hjälp` och ett kommando för mer om det, som `/hjälp bild`."
    )
    page = help_for("väder", admin=False)
    assert "`/väder` – i Stockholm\n" in page
    assert help_for("hjälp", admin=False).endswith(
        "Alla kommandon fungerar också med sina engelska namn."
    )


def test_help_fits_in_one_bubble_in_every_language() -> None:
    # Signal's apps show a message of up to 2,000 bytes whole; a longer one
    # is cut short, behind Read more
    for code in languages():
        with speaking(code):
            texts = [help_message(admin=True)]
            texts += [help_for(name, admin=True) for name in ENTRIES]
            for text in texts:
                assert len(unmarked(text)[0].encode()) <= 2000, (code, text[:40])


def test_examples_show_as_such_in_every_language() -> None:
    # A translation keeps a page's examples, each on a line of its own with
    # its ' – ', which shows it in monospace
    def examples(text: str) -> int:
        return sum(line.startswith("`") for line in text.splitlines()[1:])

    for name in ENTRIES:
        with speaking("en"):
            wanted = examples(help_for(name, admin=True))
        for code in languages():
            with speaking(code):
                assert examples(help_for(name, admin=True)) == wanted, (code, name)


def test_the_docker_hub_page_fits_and_links_in_full() -> None:
    # Docker Hub takes 25,000 bytes at most, and can't follow the repository's
    # relative links
    page = (Path(__file__).parent.parent / "DOCKERHUB.md").read_text()
    assert len(page.encode()) < 25_000
    links = re.findall(r"\]\(([^)\s]+)\)", page)
    assert links
    assert [link for link in links if not link.startswith("https://")] == []
