import os
from datetime import date, datetime
from pathlib import Path
from typing import cast

import pytest
from helpers import ALICE, make_jpeg, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot, TextMode

from nejomibot import photos
from nejomibot.onthisday import AROUND, OnThisDay, nearest, photo_on

TODAY = date(2026, 10, 19)


def test_nearest() -> None:
    assert nearest(date(2023, 10, 19), TODAY) == (0, 3)
    assert nearest(date(2024, 10, 21), TODAY) == (2, 2)
    assert nearest(date(2024, 10, 17), TODAY) == (2, 2)
    # Round New Year, in the year it's nearest
    assert nearest(date(2024, 12, 31), date(2026, 1, 2)) == (2, 1)
    # Not this year's: a year later at the nearest
    for day in (date(2026, 10, 19), date(2025, 12, 31)):
        found = nearest(day, date(2026, 1, 2) if day.year == 2025 else TODAY)
        assert found is not None and found[0] > AROUND
    assert nearest(date(2027, 1, 1), TODAY) is None
    # 29 February, in a year without it
    assert nearest(date(2024, 2, 29), date(2026, 2, 28)) == (0, 2)


def test_a_photo_from_this_day(photos_dir: Path) -> None:
    make_jpeg(photos_dir / "a.jpg", "2023:10:19 12:00:00", "+02:00")
    make_jpeg(photos_dir / "b.jpg", "2024:10:21 12:00:00", "+02:00")
    make_jpeg(photos_dir / "c.jpg", "2026:10:19 08:00:00", "+02:00")
    make_jpeg(photos_dir / "d.jpg", "2025:10:25 08:00:00", "+02:00")
    make_jpeg(photos_dir / "e.jpg")  # when, unknown
    message = photo_on(TODAY)
    assert message is not None
    assert message.text_mode == TextMode.STYLED
    assert message.base64_attachments
    # Captioned as /photo captions it, under how long ago
    assert message.text == "**3 years ago today**\n\n📅 2023-10-19 12:00"
    # Else the nearest days around it
    (photos_dir / "a.jpg").unlink()
    message = photo_on(TODAY)
    assert message is not None
    assert message.text == "**2 years ago, around this day**\n\n📅 2024-10-21 12:00"
    (photos_dir / "b.jpg").unlink()
    assert photo_on(TODAY) is None


def test_each_photo_is_read_once(
    photos_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_jpeg(photos_dir / "a.jpg", "2023:10:19 12:00:00", "+02:00")
    read: list[str] = []
    moment_taken = photos.moment_taken

    def reading(path: Path) -> datetime | None:
        read.append(path.name)
        return moment_taken(path)

    monkeypatch.setattr(photos, "moment_taken", reading)
    photo_on(TODAY)
    photo_on(TODAY)
    assert read == ["a.jpg"]
    # A photo that changes is read again
    make_jpeg(path, "2022:10:19 12:00:00", "+02:00")
    os.utime(path, ns=(0, 1))
    message = photo_on(TODAY)
    assert message is not None
    assert message.text == "**4 years ago today**\n\n📅 2022-10-19 12:00"
    assert read == ["a.jpg", "a.jpg"]


def test_a_photo_it_can_t_read(
    photos_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (photos_dir / "a.jpg").write_bytes(b"no photo")
    assert photo_on(TODAY) is None
    assert "Could not read when" in caplog.text


@pytest.mark.usefixtures("photos_dir")
async def test_the_command(answers: list[SendMessage]) -> None:
    message = message_from(ALICE, "/onthisday")
    await OnThisDay().handle_data_message(
        DataMessageContext(cast(SignalBot, None), message)
    )
    assert [answer.text for answer in answers] == [
        "No photos from this day, or the days around it, in earlier years."
    ]


async def test_from_an_album(photos_dir: Path, answers: list[SendMessage]) -> None:
    (photos_dir / "Alice").mkdir()
    make_jpeg(photos_dir / "Alice/a.jpg", "2024:10:19 12:00:00", "+02:00")
    make_jpeg(photos_dir / "b.jpg", "2023:10:19 12:00:00", "+02:00")
    message = photo_on(TODAY, "Alice")
    assert message is not None
    assert message.text == "**2 years ago today**\n\n📅 2024-10-19 12:00"
    # Without one, from every album, and the photos in none
    (photos_dir / "b.jpg").unlink()
    message = photo_on(TODAY)
    assert message is not None
    assert message.text == "**2 years ago today**\n\n📅 2024-10-19 12:00"
    for text in ("/onthisday Bob", "/onthisday alice 2"):
        await OnThisDay().handle_data_message(
            DataMessageContext(cast(SignalBot, None), message_from(ALICE, text))
        )
    assert [answer.text for answer in answers] == [
        "There's no album Bob: /albums lists them.",
        "There's no album alice 2: /albums lists them.",
    ]
