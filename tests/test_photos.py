import asyncio
import base64
import io
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image, TiffImagePlugin
from signalbot import TextMode, TextStyle

from nejomibot import photos
from nejomibot.config import get_settings
from nejomibot.styles import unmarked

# Made up, as is everyone in the tests
BORN = "2019-06-15"


@pytest.fixture
def born(monkeypatch: pytest.MonkeyPatch) -> None:
    """Captions show the age of who's in the photos, born on BORN."""
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_BIRTH_DATE", BORN)
    get_settings.cache_clear()


def make_jpeg(
    path: Path,
    taken: str | None = None,
    offset: str | None = None,
    created: str | None = None,
    where: tuple[float, float] | None = None,
) -> Path:
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[0x9003] = taken  # DateTimeOriginal
    if offset:
        exif.get_ifd(0x8769)[0x9011] = offset  # OffsetTimeOriginal
    if created:
        exif.get_ifd(0x8769)[0x9004] = created  # CreateDate (DateTimeDigitized)
    if where:
        gps = exif.get_ifd(0x8825)
        for (ref, tag), value, sides in zip(
            ((1, 2), (3, 4)), where, ("NS", "EW"), strict=True
        ):
            gps[ref] = sides[value < 0]
            gps[tag] = dms(abs(value))
    Image.new("RGB", (4, 3), "red").save(path, exif=exif)
    return path


def dms(degrees: float) -> tuple[TiffImagePlugin.IFDRational, ...]:
    """Degrees, minutes and seconds, as cameras save them."""
    minutes, seconds = divmod(round(degrees * 3600 * 100), 60 * 100)
    whole, minutes = divmod(minutes, 60)
    return (
        TiffImagePlugin.IFDRational(whole, 1),
        TiffImagePlugin.IFDRational(minutes, 1),
        TiffImagePlugin.IFDRational(seconds, 100),
    )


def caption(path: Path, heading: str = "") -> str:
    exif = photos.read_photo(path)
    assert exif is not None
    return photos.photo_caption(path, exif, heading)


def test_scan_finds_each_photo_once(photos_dir: Path) -> None:
    (photos_dir / "sub").mkdir()
    for name in ["a.jpg", "B.JPG", "c.jpeg", "sub/d.heic", "notes.txt", ".e.jpg.part"]:
        (photos_dir / name).touch()
    found = sorted(p.relative_to(photos_dir).as_posix() for p in photos.scan_photos())
    assert found == ["B.JPG", "a.jpg", "c.jpeg", "sub/d.heic"]


@pytest.mark.usefixtures("born")
def test_format_age() -> None:
    assert photos.format_age(datetime(2019, 1, 1)) == ""
    assert photos.format_age(datetime(2019, 6, 15)) == ""
    assert photos.format_age(datetime(2019, 6, 16, 23, 59)) == "🎂 1 day"
    assert photos.format_age(datetime(2019, 7, 2)) == "🎂 17 days"
    assert photos.format_age(datetime(2028, 9, 18)) == "🎂 9 years, 3 months and 3 days"
    assert photos.format_age(datetime(2020, 7, 16)) == "🎂 1 year, 1 month and 1 day"


@pytest.mark.usefixtures("born", "swedish")
def test_format_age_in_swedish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_AGE_EMOJI", "👧")
    get_settings.cache_clear()
    assert photos.format_age(datetime(2019, 6, 16, 23, 59)) == "👧 1 dag"
    assert photos.format_age(datetime(2019, 7, 2)) == "👧 17 dagar"
    assert photos.format_age(datetime(2028, 9, 18)) == "👧 9 år, 3 mån och 3 dagar"
    assert photos.format_age(datetime(2020, 7, 16)) == "👧 1 år, 1 mån och 1 dag"


def test_no_age_without_a_birth_date() -> None:
    assert photos.format_age(datetime(2028, 9, 18)) == ""


@pytest.mark.usefixtures("born")
def test_caption_is_in_the_bots_time(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg", "2020:07:01 12:00:00", "+03:00")
    assert caption(path, "Photo of the day!") == (
        "**Photo of the day!**\n\n📅 2020-07-01 11:00\n🎂 1 year and 16 days"
    )


def test_caption_of_a_photo_taken_in_sweden(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg", "2020:07:01 12:00:00", "+02:00")
    assert caption(path).startswith("📅 2020-07-01 12:00")


@pytest.mark.usefixtures("born")
def test_caption_without_offset_takes_photos_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_TIMEZONE", "Europe/Helsinki")
    get_settings.cache_clear()
    path = make_jpeg(
        tmp_path / "x.jpg", "2019:07:02 19:50:01", created="2019:07:02 19:50:01"
    )
    assert caption(path) == "📅 2019-07-02 18:50\n🎂 17 days"


def test_caption_without_offset_or_photos_timezone(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg", "2019:07:02 19:50:01")
    assert caption(path) == "📅 2019-07-02 19:50"


@pytest.mark.usefixtures("born")
@pytest.mark.parametrize("offset", [None, "+03:00"])
def test_caption_of_a_utc_original(tmp_path: Path, offset: str | None) -> None:
    # Some phones save DateTimeOriginal in UTC, whatever offset they give, and
    # CreateDate in local time
    path = make_jpeg(
        tmp_path / "x.jpg", "2020:07:01 22:30:00", offset, "2020:07:02 01:30:00"
    )
    assert caption(path) == "📅 2020-07-02 00:30\n🎂 1 year and 17 days"


def test_caption_ignores_a_create_date_far_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # e.g. the day a paper photo was scanned
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_TIMEZONE", "Europe/Helsinki")
    get_settings.cache_clear()
    path = make_jpeg(
        tmp_path / "x.jpg", "2016:05:01 10:00:00", created="2024:01:01 10:00:00"
    )
    assert caption(path) == "📅 2016-05-01 09:00"


# Stockholm's city hall, and Rio de Janeiro's Christ the Redeemer
@pytest.mark.parametrize(
    ("where", "link"),
    [
        ((59.32747, 18.05447), "https://maps.google.com/maps?q=59.32747,18.05447"),
        ((-22.95191, -43.21049), "https://maps.google.com/maps?q=-22.95191,-43.21049"),
    ],
)
def test_caption_links_to_where_it_was_taken(
    tmp_path: Path, where: tuple[float, float], link: str
) -> None:
    path = make_jpeg(tmp_path / "x.jpg", "2020:07:01 12:00:00", "+02:00", where=where)
    assert caption(path) == f"📅 2020-07-01 12:00\n\n{link}"


@pytest.mark.parametrize(
    ("where", "link"),
    [
        # As osm.org decodes them: 59.32746,18.05446 and -22.95192,-43.21049
        ((59.32747, 18.05447), "https://osm.org/go/0bC2KJ9q?m="),
        ((-22.95191, -43.21049), "https://osm.org/go/OVcxZ7U2?m="),
    ],
)
def test_caption_links_to_openstreetmap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: tuple[float, float],
    link: str,
) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_MAP", "openstreetmap")
    get_settings.cache_clear()
    path = make_jpeg(tmp_path / "x.jpg", "2020:07:01 12:00:00", "+02:00", where=where)
    assert caption(path).endswith(f"\n\n{link}")


def test_osm_codes_for_other_zooms() -> None:
    # A character for each three zoom levels, and a - for each short of the
    # next; as osm.org decodes them
    assert photos.osm_code(51.5108, 0.0549, 9) == "0EEQhu--"
    assert photos.osm_code(51.5108, 0.0549, 10) == "0EEQhu"
    assert photos.osm_code(51.5108, 0.0549, 11) == "0EEQhuq-"


def test_caption_without_date(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg")
    assert caption(path) == "⚠️ Date unknown (see the file name)\n🖼️ x.jpg"


@pytest.mark.usefixtures("swedish")
def test_caption_without_date_in_swedish(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg")
    assert caption(path) == "⚠️ Datum okänt (se filnamn)\n🖼️ x.jpg"


def test_the_caption_is_styled(
    photos_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_MAP", "openstreetmap")
    get_settings.cache_clear()
    make_jpeg(photos_dir / "a*b~.jpg", where=(59.0, 17.07))
    message = photos.random_photo_message("Photo of the day!")
    assert message is not None
    assert message.text_mode == TextMode.STYLED
    # As signal-cli-rest-api reads it: the heading in bold, the rest, and the
    # link with its ~, as it is
    assert unmarked(message.text or "") == (
        "Photo of the day!\n\n"
        "⚠️ Date unknown (see the file name)\n🖼️ a*b~.jpg\n\n"
        "https://osm.org/go/0aVcSy~_?m=",
        [TextStyle(start=0, length=17, style="BOLD")],
    )


def test_random_photo_skips_broken_files(photos_dir: Path) -> None:
    (photos_dir / "broken.jpg").write_bytes(b"not an image")
    good = make_jpeg(photos_dir / "good.jpeg")
    message = photos.random_photo_message()
    assert message is not None
    assert message.base64_attachments == [base64.b64encode(good.read_bytes()).decode()]


def test_random_photo_with_no_photos(photos_dir: Path) -> None:
    assert photos.random_photo_message() is None


def test_photo_stats(photos_dir: Path) -> None:
    make_jpeg(photos_dir / "a.jpg")
    make_jpeg(photos_dir / "b.JPG")
    lines = photos.photo_stats().splitlines()
    assert lines[0].startswith("📂 Photo cache contains 2 photos")
    assert lines[1].startswith("JPG: 2 files")


async def test_cache_message_reports_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def photo_stats() -> str:
        raise FileNotFoundError("a.jpg")

    monkeypatch.setattr(photos, "photo_stats", photo_stats)
    assert await photos.cache_message() == "Something went wrong: a.jpg"


def sent_names() -> list[str]:
    return photos.get_settings().sent_photos_file.read_text().splitlines()


def test_each_photo_once_per_round(photos_dir: Path) -> None:
    (photos_dir / "sub").mkdir()
    for name in ["a.jpg", "b.jpg", "sub/c.jpg"]:
        make_jpeg(photos_dir / name)
    for _ in range(3):
        assert photos.random_photo_message(track_sent=True) is not None
    assert sorted(sent_names()) == ["a.jpg", "b.jpg", "sub/c.jpg"]

    photos.random_photo_message(track_sent=True)  # all sent: a new round starts
    assert len(sent_names()) == 1


def test_new_photo_joins_the_round(photos_dir: Path) -> None:
    make_jpeg(photos_dir / "a.jpg")
    make_jpeg(photos_dir / "b.jpg")
    photos.get_settings().sent_photos_file.write_text("a.jpg\ngone.jpg\n")
    photos.random_photo_message(track_sent=True)
    assert sent_names() == ["a.jpg", "gone.jpg", "b.jpg"]


def test_broken_photo_counts_as_sent(photos_dir: Path) -> None:
    (photos_dir / "broken.jpg").write_bytes(b"not an image")
    assert photos.random_photo_message(track_sent=True) is None
    assert sent_names() == ["broken.jpg"]
    # The next try starts a new round instead of being stuck
    assert photos.random_photo_message(track_sent=True) is None
    assert sent_names() == ["broken.jpg"]


def test_commands_ignore_the_sent_photos(photos_dir: Path) -> None:
    make_jpeg(photos_dir / "a.jpg")
    photos.get_settings().sent_photos_file.write_text("a.jpg\n")
    assert photos.random_photo_message() is not None
    assert sent_names() == ["a.jpg"]


def test_heif_is_sent_as_jpeg(photos_dir: Path) -> None:
    Image.new("RGB", (4, 3), "red").save(photos_dir / "x.heic")
    message = photos.random_photo_message()
    assert message is not None
    [attachment] = message.base64_attachments or []
    data = base64.b64decode(str(attachment))
    with Image.open(io.BytesIO(data)) as img:
        assert (img.format, img.size) == ("JPEG", (4, 3))


def test_jpeg_is_sent_unchanged(photos_dir: Path) -> None:
    path = make_jpeg(photos_dir / "x.JPG")
    assert photos.photo_bytes(path) == path.read_bytes()


async def test_photo_message_without_photos(photos_dir: Path) -> None:
    message = await photos.photo_message()
    assert message.text == "Something went wrong: found no photo that could be sent"


def test_heif_can_be_left_out(
    photos_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_HEIF", "false")
    get_settings.cache_clear()
    for name in ["a.jpg", "b.heic", "c.HEIF"]:
        (photos_dir / name).touch()
    assert [p.name for p in photos.scan_photos()] == ["a.jpg"]


async def test_two_daily_posts_at_once_pick_two_photos(photos_dir: Path) -> None:
    for name in ["a.jpg", "b.jpg"]:
        make_jpeg(photos_dir / name)
    picked = await asyncio.gather(
        *(
            asyncio.to_thread(photos.random_photo_message, track_sent=True)
            for _ in range(2)
        )
    )
    assert sorted(m.text or "" for m in picked if m) == [
        "⚠️ Date unknown (see the file name)\n🖼️ a.jpg",
        "⚠️ Date unknown (see the file name)\n🖼️ b.jpg",
    ]
    assert sorted(sent_names()) == ["a.jpg", "b.jpg"]


def test_the_sent_photos_are_listed_privately(photos_dir: Path) -> None:
    make_jpeg(photos_dir / "Åre.jpg")
    photos.random_photo_message(track_sent=True)
    sent_file = get_settings().sent_photos_file
    assert sent_file.read_text(encoding="utf-8") == "Åre.jpg\n"
    assert sent_file.stat().st_mode & 0o777 == 0o600
