from datetime import date
from pathlib import Path
from typing import cast

import pytest
from helpers import ALICE, make_jpeg, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import photos
from nejomibot.albums import Album, Albums, album_usage
from nejomibot.commands import Handler
from nejomibot.config import get_settings


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
    """photos_birth_date, for the albums without one of their own."""
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_BIRTH_DATE", "2018-01-01")
    get_settings.cache_clear()


@pytest.mark.usefixtures("library")
async def test_the_albums(answers: list[SendMessage]) -> None:
    photos.birth_dates.add(photos.BirthDate("Alice", date(2019, 6, 15)))
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
    photos.birth_dates.add(photos.BirthDate("Alice", date(2019, 6, 15)))
    await send(Album(), "/album ALICE")
    assert texts(answers) == [
        "📖 **Alice**\n3 photos · 2019–2021\n🎂 No birth date, so its captions show "
        "no age",
        "📖 **Bob and Carol**\n1 photo · 2024\n🎂 Born 2018-01-01, as "
        "photos_birth_date has it",
        "📖 **Alice**\n3 photos · 2019–2021\n🎂 Born 2019-06-15",
    ]


@pytest.mark.usefixtures("library")
async def test_an_albums_birth_date(answers: list[SendMessage]) -> None:
    await send(Album(), "/album alice 2019-06-15")
    await send(Album(), "/album Alice 2019-06-16")  # a change, in the same line
    assert photos.birth_date("Alice") == date(2019, 6, 16)
    assert photos.birth_dates.current().entries == [
        photos.BirthDate("Alice", date(2019, 6, 16))
    ]
    assert (
        get_settings()
        .data_file("albums.txt")
        .read_text()
        .endswith("\nAlice | 2019-06-16\n")
    )
    await send(Album(), "/album Alice -")
    await send(Album(), "/album Alice -")
    assert photos.birth_date("Alice") is None
    assert texts(answers) == [
        "✅ Alice: born 2019-06-15, so its captions show the age.",
        "✅ Alice: born 2019-06-16, so its captions show the age.",
        "✅ Alice: no birth date, so its captions show no age.",
        "Alice has no birth date of its own.",
    ]


@pytest.mark.usefixtures("library", "born")
async def test_without_its_own_photos_birth_date_counts(
    answers: list[SendMessage],
) -> None:
    await send(Album(), "/album Alice 2019-06-15")
    await send(Album(), "/album Alice -")
    assert photos.birth_date("Alice") == date(2018, 1, 1)
    assert texts(answers)[1] == (
        "✅ Alice: no birth date of its own, so photos_birth_date's, 2018-01-01, "
        "counts."
    )


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
    assert photos.birth_dates.current().entries == []


@pytest.mark.usefixtures("library")
async def test_an_edit_takes_the_place_of_a_birth_date(
    answers: list[SendMessage],
) -> None:
    await send(Album(), "/album Alice 2019-06-15")
    await send(Album(), "/album Bob and Carol 2024-05-01", edit=True)
    assert photos.birth_date("Alice") is None
    assert photos.birth_date("Bob and Carol") == date(2024, 5, 1)
