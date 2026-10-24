"""The translations: complete, and true to the messages they translate."""

import ast
import re
import string
import sys
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polib
import pytest

from nejomibot import commands, i18n, reminders, timers
from nejomibot.commands import known
from nejomibot.config import get_settings
from nejomibot.i18n import (
    COMMAND_SLASH,
    LOCALE_DIR,
    _,
    every_word,
    languages,
    ngettext,
    prefixed,
    shown_word,
    weekday_and_day,
    when_text,
)

PACKAGE = Path(i18n.__file__).parent

type Message = tuple[str, str | None]  # a message, and its plural if it has one


def messages_in_the_code() -> set[Message]:
    """What _(), N_() and ngettext() are given, as tools/translations.sh
    finds it with xgettext."""
    found: set[Message] = set()
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            texts = [
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            if node.func.id in ("_", "N_") and texts:
                found.add((texts[0], None))
            elif node.func.id == "ngettext" and len(texts) == 2:
                found.add((texts[0], texts[1]))
    return found


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def po_files() -> list[Path]:
    return sorted(LOCALE_DIR.glob("*.po"))


def command_names() -> set[str]:
    """Every command's English name, as the handlers list them."""
    return {
        command.name.split()[0]
        for handler in commands.handlers()
        for command in handler.commands
    }


def words_read() -> set[str]:
    """The English words the bot reads in commands, which a language's .toml
    may give words of its own for."""
    return {
        *timers.DAY_NAMES,
        *timers.FULL_DAY_NAMES,
        *timers.DAY_SETS,
        *timers.DAYS_FROM_NOW,
        timers.EVERY,
        reminders.IN,
        # Subcommands, as the handlers list them
        *(
            word
            for handler in commands.handlers()
            for command in handler.commands
            for word in (*command.subcommands, *command.name.split()[1:])
        ),
    }


def test_there_are_messages_to_translate() -> None:
    assert len(messages_in_the_code()) > 300
    assert languages() == ["en", *(path.stem for path in po_files())]
    assert "sv" in languages()


@pytest.mark.parametrize("path", po_files(), ids=lambda path: path.name)
def test_every_message_is_translated(path: Path) -> None:
    po = polib.pofile(str(path))
    translated = {(e.msgid, e.msgid_plural or None) for e in po.translated_entries()}
    in_the_code = messages_in_the_code()
    assert sorted(in_the_code - translated, key=str) == [], "untranslated or fuzzy"
    assert sorted(translated - in_the_code, key=str) == [], "no longer in the code"


@pytest.mark.parametrize("path", po_files(), ids=lambda path: path.name)
def test_translations_have_the_same_fields(path: Path) -> None:
    po = polib.pofile(str(path))
    # As many plural forms as the language has, as its header says
    plurals = re.fullmatch(
        r"nplurals=(\d+); *plural=[^;]+;?", po.metadata["Plural-Forms"].strip()
    )
    assert plurals, "Plural-Forms"
    for entry in po.translated_entries():
        if entry.msgid_plural:
            forms = [entry.msgstr_plural[n] for n in sorted(entry.msgstr_plural)]
            assert len(forms) == int(plurals[1]), entry.msgid
            # None with a field the code doesn't fill in; the last, for most
            # numbers, with all of them
            for form in forms:
                assert fields(form) <= fields(entry.msgid_plural), entry.msgid
            assert fields(forms[-1]) == fields(entry.msgid_plural), entry.msgid
        else:
            assert fields(entry.msgstr) == fields(entry.msgid), entry.msgid


def test_the_templates_are_current() -> None:
    # What a new language starts from, as tools/translations.sh writes it
    pot = polib.pofile(str(LOCALE_DIR / "messages.pot"))
    assert {(e.msgid, e.msgid_plural or None) for e in pot} == messages_in_the_code()
    names = tomllib.loads((LOCALE_DIR / "template.toml").read_text())
    assert set(names) == {"name", "commands", "words"}
    assert names["name"] == ""
    assert set(names["commands"]) == command_names()
    assert set(names["words"]) == words_read()
    assert not any([*names["commands"].values(), *names["words"].values()])


# The made-up names of specials and shortcuts in the messages' examples
EXAMPLES = {"/morning", "/gm", "/alice"}


def test_the_prefix_shows_only_commands() -> None:
    # Every / it shows as a . starts a command's name, or an example's: no
    # path, nor anything else. A translation has as many as its message.
    names = {*EXAMPLES, *command_names(), *commands.aliases()}
    for message, plural in messages_in_the_code():
        for text in filter(None, [message, plural]):
            for found in COMMAND_SLASH.finditer(text):
                name = text[found.start() :].split()[0].rstrip(".,:;)")
                assert name.casefold() in names, text
    for path in po_files():
        for entry in polib.pofile(str(path)).translated_entries():
            source = entry.msgid_plural or entry.msgid
            for text in [entry.msgstr, *entry.msgstr_plural.values()]:
                if text:
                    count = len(COMMAND_SLASH.findall(text))
                    assert count == len(COMMAND_SLASH.findall(source)), text


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("/photo", ".photo"),
        (
            "(/pic) /timer add 08:00 1,2 /weather; /photo",
            "(.pic) .timer add 08:00 1,2 .weather; .photo",
        ),
        # Only a / that starts a word, before a letter
        ("3/4 km/h {failed}/{count} https://example.com/a /5", None),
    ],
)
def test_prefixed(
    text: str, shown: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert prefixed(text) == text  # as the tests' config has it: /
    monkeypatch.setenv("NEJOMIBOT_COMMAND_PREFIX", ".")
    get_settings.cache_clear()
    assert prefixed(text) == (shown or text)


@pytest.mark.usefixtures("swedish")
def test_messages_show_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_COMMAND_PREFIX", ".")
    get_settings.cache_clear()
    hint = _("For /timer add, e.g. /timer add 08:00 1,2 /weather; /photo")
    assert (
        hint == "För .timer lägg till, t.ex. .timer lägg till 08:00 1,2 .väder; .bild"
    )


def test_english_is_as_written() -> None:
    assert _("a random photo") == "a random photo"
    assert ngettext("{n} day", "{n} days", 1) == "{n} day"
    assert ngettext("{n} day", "{n} days", 2) == "{n} days"
    # Every language's words are read, its own shown
    assert every_word("mon")[0] == "mon"
    assert "mån" in every_word("mon")
    assert shown_word("mon") == "mon"


def test_when_text() -> None:
    now = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)  # 08:00 in Stockholm
    assert when_text(now, now) == "08:00"
    assert when_text(now - timedelta(hours=8), now) == "00:00"
    assert when_text(now - timedelta(hours=8, minutes=1), now) == "yesterday 23:59"
    assert when_text(now - timedelta(days=1, hours=8), now) == "yesterday 00:00"
    assert when_text(now - timedelta(days=1, hours=9), now) == "2026-10-10 23:00"


@pytest.mark.usefixtures("swedish")
def test_swedish() -> None:
    assert _("a random photo") == "en slumpvis vald bild"
    assert ngettext("{n} day", "{n} days", 1) == "{n} dag"
    assert ngettext("{n} day", "{n} days", 2) == "{n} dagar"
    assert ngettext("{n} day", "{n} days", 0) == "{n} dagar"
    assert every_word("mon")[0] == "mon"
    assert shown_word("mon") == "mån"
    now = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
    assert when_text(now - timedelta(hours=9), now) == "igår 23:00"


@pytest.mark.parametrize("language", languages())
def test_the_languages_names_are_for_real_commands_and_words(
    language: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", language)
    get_settings.cache_clear()
    names = i18n.language()
    for command, aliases in names.commands.items():
        assert command in command_names(), command
        for alias in aliases:
            assert alias == alias.strip() and alias.startswith("/"), command
            assert not known(alias), alias
    assert set(names.words) <= words_read()


def test_the_image_reads_them_compiled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As the Dockerfile leaves them: a .mo for each .po, which is gone, as
    # is polib
    (tmp_path / "sv.toml").write_bytes((LOCALE_DIR / "sv.toml").read_bytes())
    polib.pofile(str(LOCALE_DIR / "sv.po")).save_as_mofile(str(tmp_path / "sv.mo"))
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "polib", None)
    i18n.load.cache_clear()
    i18n.names_of.cache_clear()
    languages.cache_clear()
    try:
        swedish = i18n.load("sv")
        assert languages() == ["en", "sv"]
    finally:
        i18n.load.cache_clear()
        i18n.names_of.cache_clear()
        languages.cache_clear()
    assert swedish.translations.gettext("a random photo") == "en slumpvis vald bild"
    assert swedish.translations.ngettext("{n} day", "{n} days", 2) == "{n} dagar"
    assert swedish.commands["/photo"] == ["/bild", "/foto"]


def test_a_new_language_is_its_files_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As tools/translations.sh xx starts one, from the templates, msginit
    # giving the .po its language and plural forms; then a name or two
    po = polib.pofile(str(LOCALE_DIR / "messages.pot"))
    po.metadata.update(Language="xx", **{"Plural-Forms": "nplurals=1; plural=0;"})
    po.save(str(tmp_path / "xx.po"))
    names = (LOCALE_DIR / "template.toml").read_text()
    names = names.replace('name = ""', 'name = "Xx"').replace(
        '"/photo" = []', '"/photo" = ["/xphoto"]'
    )
    (tmp_path / "xx.toml").write_text(names)
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", "xx")
    get_settings.cache_clear()
    for cached in (i18n.load, i18n.names_of, languages):
        cached.cache_clear()
    try:
        assert languages() == ["en", "xx"]
        assert i18n.language().name == "Xx"
        assert commands.canonical("/xphoto 2017") == "/photo 2017"
        # In English, till it's translated
        assert _("a random photo") == "a random photo"
        assert ngettext("{n} day", "{n} days", 2) == "{n} days"
    finally:
        for cached in (i18n.load, i18n.names_of, languages):
            cached.cache_clear()


def test_a_broken_names_file_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for path in LOCALE_DIR.glob("sv.*"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / "sv.toml").write_text('[comands]\n"/photo" = ["/bild"]\n')
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    i18n.load.cache_clear()
    i18n.names_of.cache_clear()
    try:
        with pytest.raises(ValueError, match="comands"):
            i18n.load("sv")
    finally:
        i18n.load.cache_clear()
        i18n.names_of.cache_clear()


def test_greek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", "el")
    get_settings.cache_clear()
    assert _("a random photo") == "μια τυχαία φωτογραφία"
    assert ngettext("{n} day", "{n} days", 2) == "{n} μέρες"
    # The month in the genitive, as a date has it
    assert weekday_and_day(date(2026, 10, 25)) == "Κυριακή 25 Οκτωβρίου"
    # Its names for commands and words, with accents or without
    assert commands.canonical("/καιρός Αθήνα") == "/weather Αθήνα"
    assert commands.canonical("/λιστα πρόσθεσε γάλα") == "/list add γάλα"
    schedule = timers.parse_when("δευ-παρ 07:30", datetime.now(UTC))
    assert isinstance(schedule, timers.Schedule)
    assert schedule.days == frozenset(range(5))
    assert timers.shown(schedule.text) == "εργάσιμες 07:30"
