from datetime import date
from pathlib import Path
from typing import cast

import pytest
from helpers import ALICE, make_jpeg, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import photos
from nejomibot.albums import Album, Albums, album_usage
from nejomibot.commands import Handler, aliases, canonical
from nejomibot.config import get_settings
from nejomibot.photos import AlbumSettings, Photo, album_settings
from nejomibot.specials import Specials


def make(photos_dir: Path, name: str, taken: str | None = None) -> None:
    """A photo at that path in the library, taken then, in Swedish time."""
    path = photos_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    make_jpeg(path, taken, "+02:00" if taken else None)


async def send(handler: Handler, text: str, *, edit: bool = False) -> None:
    message = message_from(ALICE, text, edit=edit)
    await handler.handle_data_message(
        DataMessageContext(cast(SignalBot, None), message)
    )


def texts(answers: list[SendMessage]) -> list[str | None]:
    return [answer.text for answer in answers]


def albums_file() -> str:
    return get_settings().data_file("albums.txt").read_text()


@pytest.fixture
def library(photos_dir: Path) -> Path:
    """Two albums, one with a space in its name, and a photo in none."""
    make(photos_dir, "Alice/a.jpg", "2019:07:01 12:00:00")
    make(photos_dir, "Alice/2021/b.jpg", "2021:01:01 12:00:00")
    make(photos_dir, "Alice/c.jpg")  # when, unknown
    make(photos_dir, "Bob and Carol/d.jpg", "2024:06:01 12:00:00")
    make(photos_dir, "e.jpg")
    return photos_dir


@pytest.fixture
def born(monkeypatch: pytest.MonkeyPatch) -> None:
    """photos_birth_date, for the photos in no album."""
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_BIRTH_DATE", "2018-01-01")
    get_settings.cache_clear()


@pytest.mark.usefixtures("library")
async def test_the_albums(answers: list[SendMessage]) -> None:
    album_settings.add(AlbumSettings("Alice", date(2019, 6, 15)))
    await send(Albums(), "/albums")
    assert texts(answers) == [
        "**📚 2 albums**\n"
        "**Alice** · 3 photos · 2019–2021 · 🎂 2019-06-15\n"
        "**Bob and Carol** · 1 photo · 2024\n"
        "📷 1 photo in no album"
    ]


async def test_no_albums(photos_dir: Path, answers: list[SendMessage]) -> None:
    make(photos_dir, "e.jpg")
    await send(Albums(), "/albums")
    assert texts(answers) == [
        "📚 No albums: each folder in the photo library is one.\n📷 1 photo in no album"
    ]


@pytest.mark.usefixtures("library")
async def test_an_album(
    answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    await send(Album(), "/album alice")
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_BIRTH_DATE", "2018-01-01")
    get_settings.cache_clear()
    await send(Album(), "/album Bob and Carol")
    album_settings.add(AlbumSettings("Alice", date(2019, 6, 15)))
    await send(Album(), "/album ALICE")
    assert texts(answers) == [
        "📖 **Alice**\n3 photos · 2019–2021\n🎂 No birth date, so its captions show "
        "no age\n🏷️ No shortcuts",
        # Not photos_birth_date's: an album has none until it's set
        "📖 **Bob and Carol**\n1 photo · 2024\n🎂 No birth date, so its captions "
        "show no age\n🏷️ No shortcuts",
        "📖 **Alice**\n3 photos · 2019–2021\n🎂 Born 2019-06-15\n🏷️ No shortcuts",
    ]


@pytest.mark.usefixtures("library")
async def test_an_albums_birth_date(answers: list[SendMessage]) -> None:
    await send(Album(), "/album alice 2019-06-15")
    await send(Album(), "/album Alice 2019-06-16")  # a change, in the same line
    assert photos.birth_date("Alice") == date(2019, 6, 16)
    assert album_settings.current().entries == [
        AlbumSettings("Alice", date(2019, 6, 16))
    ]
    assert albums_file().endswith("\nAlice | 2019-06-16 |\n")
    await send(Album(), "/album Alice -")
    await send(Album(), "/album Alice -")
    assert photos.birth_date("Alice") is None
    assert texts(answers) == [
        "✅ Alice: born 2019-06-15, so its captions show the age.",
        "✅ Alice: born 2019-06-16, so its captions show the age.",
        "✅ Alice: no birth date, so its captions show no age.",
        "Alice has no birth date.",
    ]


@pytest.mark.usefixtures("library", "born")
async def test_photos_birth_date_is_for_photos_in_no_album(
    answers: list[SendMessage],
) -> None:
    await send(Album(), "/album Alice 2019-06-15")
    await send(Album(), "/album Alice -")
    await send(Albums(), "/albums")
    assert photos.birth_date("Alice") is None
    assert photos.birth_date(None) == date(2018, 1, 1)
    assert texts(answers)[1:] == [
        "✅ Alice: no birth date, so its captions show no age.",
        "**📚 2 albums**\n"
        "**Alice** · 3 photos · 2019–2021\n"
        "**Bob and Carol** · 1 photo · 2024\n"
        "📷 1 photo in no album",
    ]


@pytest.mark.usefixtures("library")
async def test_what_album_can_t_read(answers: list[SendMessage]) -> None:
    for text in (
        "/album",
        "/album Dave 2019-06-15",
        "/album Dave",
        "/album Alice 2019-02-30",
        "/album Alice soon",
    ):
        await send(Album(), text)
    assert texts(answers) == [
        album_usage(),
        "There's no album Dave: /albums lists them.",
        "There's no album Dave: /albums lists them.",
        "2019-02-30 isn't a date, as 2019-06-15.",
        "soon isn't a date, as 2019-06-15.",
    ]
    assert album_settings.current().entries == []


@pytest.mark.usefixtures("library")
async def test_an_edit_takes_the_place_of_a_birth_date(
    answers: list[SendMessage],
) -> None:
    await send(Album(), "/album Alice 2019-06-15")
    await send(Album(), "/album Bob and Carol 2024-05-01", edit=True)
    assert photos.birth_date("Alice") is None
    assert photos.birth_date("Bob and Carol") == date(2024, 5, 1)


@pytest.mark.usefixtures("library")
async def test_an_albums_shortcuts(answers: list[SendMessage]) -> None:
    await send(Album(), "/album alice shortcuts /alice .al")
    assert albums_file().endswith("\nAlice |  | /alice /al\n")
    # Each another name for /photo with the album, and what follows it
    assert aliases()["/al"] == "/photo Alice"
    assert canonical("/ALICE") == "/photo Alice"
    assert canonical(".alice 2021") == "/photo Alice 2021"
    await send(Photo(), "/al 2021")
    # A birth date keeps them
    await send(Album(), "/album Alice 2019-06-15")
    assert album_settings.current().entries == [
        AlbumSettings("Alice", date(2019, 6, 15), ("/alice", "/al"))
    ]
    await send(Album(), "/album Alice")
    await send(Albums(), "/albums")
    shortcuts, photo, _born, album, listed = texts(answers)
    assert shortcuts == "✅ Shortcuts for /photo Alice: /alice, /al."
    assert (photo or "").startswith("📅 2021-01-01")
    assert album == (
        "📖 **Alice**\n3 photos · 2019–2021\n🎂 Born 2019-06-15\n🏷️ Shortcuts: "
        "/alice, /al"
    )
    assert (listed or "").splitlines()[1] == (
        "**Alice** · 3 photos · 2019–2021 · 🎂 2019-06-15 · 🏷️ /alice /al"
    )
    answers.clear()
    await send(Album(), "/album Alice shortcuts -")
    await send(Album(), "/album Alice shortcuts -")
    assert albums_file().endswith("\nAlice | 2019-06-15 |\n")
    assert "/al" not in aliases()
    # With nothing of its own left, no line
    await send(Album(), "/album Alice -")
    assert album_settings.current().entries == []
    assert texts(answers) == [
        "✅ Alice: no shortcuts.",
        "Alice has no shortcuts.",
        "✅ Alice: no birth date, so its captions show no age.",
    ]


@pytest.mark.usefixtures("library")
async def test_a_shortcut_cant_hide_a_name(
    answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic"]}')
    get_settings.cache_clear()
    get_settings().data_file("specials.txt").write_text("/morning /gm | Morning!\n")
    await send(Album(), "/album Bob and Carol shortcuts /bc")
    answers.clear()
    for text in (
        "/album Alice shortcuts /photo",
        "/album Alice shortcuts /idag",  # Swedish for /today
        "/album Alice shortcuts /test",  # the bot's own alias
        "/album Alice shortcuts /morning",
        "/album Alice shortcuts /pic",
        "/album Alice shortcuts /a /BC",
        "/album Alice shortcuts /GM",  # the special's
        "/album Alice shortcuts a|b",
        "/album Alice shortcuts a b c d e f",
        "/album Alice shortcuts",
    ):
        await send(Album(), text)
    assert texts(answers) == [
        "/photo is a command already.",
        "/idag is a command already.",
        "/test is a command already.",
        "/morning is a command already.",
        "/pic is an alias in the config: take it out there first.",
        "/BC is a shortcut for Bob and Carol already.",
        "/GM is a shortcut for /morning already.",
        "A shortcut can't have a \\| or a ;.",  # escaped, as the answer is styled
        "An album has at most 5 shortcuts.",
        album_usage(),
    ]
    assert album_settings.current().entries == [
        AlbumSettings("Bob and Carol", None, ("/bc",))
    ]
    # Nor can a special take a shortcut's name
    answers.clear()
    await send(Specials(), "/special add /bc Hi!")
    assert texts(answers) == ["/bc is a command already."]


@pytest.mark.usefixtures("library")
async def test_shortcuts_in_swedish(
    answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", "sv")
    get_settings.cache_clear()
    await send(Album(), "/album Alice genvägar /a")
    await send(Album(), "/album Dave genväg /a")
    assert canonical("/a") == "/photo Alice"
    assert (texts(answers)[1] or "").startswith("Det finns inget album Dave:")


@pytest.mark.usefixtures("library", "answers")
async def test_an_edit_takes_the_place_of_shortcuts() -> None:
    await send(Album(), "/album Alice shortcuts /a")
    await send(Album(), "/album Alice shortcuts /b", edit=True)
    assert "/a" not in aliases()
    assert aliases()["/b"] == "/photo Alice"


def test_the_file_of_albums() -> None:
    get_settings().data_file("albums.txt").write_text(
        "Alice | 2019-06-15\n"  # as 0.99.13 wrote it
        "Bob |  | /bob bob .bo\n"  # a plain word as before 0.99.20
        "Carol | | /photo\n"  # a command, which the shortcut would hide
        "Dave |\n"  # nothing
    )
    kept = album_settings.current()
    assert kept.entries == [
        AlbumSettings("Alice", date(2019, 6, 15)),
        # The plain word with its /, once
        AlbumSettings("Bob", None, ("/bob", "/bo")),
    ]
    assert kept.broken == ["Carol | | /photo", "Dave |"]
    assert canonical("/bob") == canonical(".BOB") == "/photo Bob"
    assert canonical("bob") == "bob"


@pytest.mark.usefixtures("library")
async def test_a_plain_word_shortcut_is_taken_with_a_slash(
    answers: list[SendMessage],
) -> None:
    await send(Album(), "/album Alice shortcuts alice")
    assert albums_file().endswith("\nAlice |  | /alice\n")
    answers.clear()
    # A message that starts with the word is no command, as it was before
    await send(Photo(), "Alice slept all day")
    assert answers == []
    await send(Photo(), ".alice 2021")
    assert (texts(answers)[0] or "").startswith("📅 2021-01-01")
