import asyncio
import base64
import io
from datetime import date, datetime
from pathlib import Path
from typing import cast

import pytest
from helpers import ALICE, make_jpeg, message_from
from PIL import Image
from signalbot import DataMessageContext, SendMessage, SignalBot, TextMode, TextStyle

from nejomibot import photos
from nejomibot.config import get_settings
from nejomibot.styles import unmarked

# Made up, as is everyone in the tests
BORN = date(2019, 6, 15)


@pytest.fixture
def born(monkeypatch: pytest.MonkeyPatch) -> None:
    """Captions show the age of who's in the photos, born on BORN."""
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_BIRTH_DATE", f"{BORN}")
    get_settings.cache_clear()


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


def test_scan_lists_what_walk_does(photos_dir: Path) -> None:
    for name in ["a.jpg", "x/b.jpg", "x/y/c.jpg", "x/z/d.jpg", "w/e.jpg"]:
        (photos_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (photos_dir / name).touch()
    (photos_dir / "link.jpg").symlink_to(photos_dir / "a.jpg")
    (photos_dir / "folder.jpg").symlink_to(photos_dir / "x")  # listed, not read
    walked = [
        dirpath / name
        for dirpath, _dirs, names in photos_dir.walk()
        for name in names
        if name.lower().endswith(photos.extensions())
    ]
    assert len(walked) == 7
    assert photos.scan_photos() == walked
    assert [str(p) for p in photos.scan_photos()] == [str(p) for p in walked]


def test_scan_without_a_library(photos_dir: Path) -> None:
    photos_dir.rmdir()
    assert photos.scan_photos() == []


def test_format_age() -> None:
    def age(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> str:
        return photos.format_age(datetime(year, month, day, hour, minute), BORN)

    assert age(2019, 1, 1) == ""
    assert age(2019, 6, 15) == ""
    assert age(2019, 6, 16, 23, 59) == "🎂 1 day"
    assert age(2019, 7, 2) == "🎂 17 days"
    assert age(2028, 9, 18) == "🎂 9 years, 3 months and 3 days"
    assert age(2020, 7, 16) == "🎂 1 year, 1 month and 1 day"


@pytest.mark.usefixtures("swedish")
def test_format_age_in_swedish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_AGE_EMOJI", "👧")
    get_settings.cache_clear()

    def age(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> str:
        return photos.format_age(datetime(year, month, day, hour, minute), BORN)

    assert age(2019, 6, 16, 23, 59) == "👧 1 dag"
    assert age(2019, 7, 2) == "👧 17 dagar"
    assert age(2028, 9, 18) == "👧 9 år, 3 mån och 3 dagar"
    assert age(2020, 7, 16) == "👧 1 år, 1 mån och 1 dag"


def test_no_age_without_a_birth_date() -> None:
    assert photos.format_age(datetime(2028, 9, 18), None) == ""


@pytest.mark.usefixtures("born")
def test_caption_is_in_the_bots_time(photos_dir: Path) -> None:
    path = make_jpeg(photos_dir / "x.jpg", "2020:07:01 12:00:00", "+03:00")
    assert caption(path, "Photo of the day!") == (
        "**Photo of the day!**\n\n📅 2020-07-01 11:00\n🎂 1 year and 16 days"
    )


def test_caption_of_a_photo_taken_in_sweden(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg", "2020:07:01 12:00:00", "+02:00")
    assert caption(path).startswith("📅 2020-07-01 12:00")


@pytest.mark.usefixtures("born")
def test_caption_without_offset_takes_photos_timezone(
    photos_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_PHOTOS_TIMEZONE", "Europe/Helsinki")
    get_settings.cache_clear()
    path = make_jpeg(
        photos_dir / "x.jpg", "2019:07:02 19:50:01", created="2019:07:02 19:50:01"
    )
    assert caption(path) == "📅 2019-07-02 18:50\n🎂 17 days"


def test_caption_without_offset_or_photos_timezone(tmp_path: Path) -> None:
    path = make_jpeg(tmp_path / "x.jpg", "2019:07:02 19:50:01")
    assert caption(path) == "📅 2019-07-02 19:50"


@pytest.mark.usefixtures("born")
@pytest.mark.parametrize("offset", [None, "+03:00"])
def test_caption_of_a_utc_original(photos_dir: Path, offset: str | None) -> None:
    # Some phones save DateTimeOriginal in UTC, whatever offset they give, and
    # CreateDate in local time
    path = make_jpeg(
        photos_dir / "x.jpg", "2020:07:01 22:30:00", offset, "2020:07:02 01:30:00"
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
    def photo_stats(album: str | None = None, library: list[Path] | None = None) -> str:
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


async def send(text: str) -> None:
    context = DataMessageContext(cast(SignalBot, None), message_from(ALICE, text))
    await photos.Photo().handle_data_message(context)


async def test_uniquephoto_is_from_the_round(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    for name in ["a.jpg", "b.jpg"]:
        make_jpeg(photos_dir / name)
    get_settings().sent_photos_file.write_text("a.jpg\n")

    await send("/uniquephoto")
    assert [answer.text for answer in answers] == [
        "⚠️ Date unknown (see the file name)\n🖼️ b.jpg"
    ]
    assert sent_names() == ["a.jpg", "b.jpg"]
    # /photo picks from all of them, and doesn't count
    await send("/photo")
    assert len(answers) == 2
    assert sent_names() == ["a.jpg", "b.jpg"]


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
    assert message == "Something went wrong: found no photo that could be sent"


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


def make_photos(photos_dir: Path, *names: str, taken: str | None = None) -> None:
    """Photos at these paths in the library, taken then, in Swedish time."""
    for name in names:
        path = photos_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        make_jpeg(path, taken, "+02:00" if taken else None)


def test_library_names(photos_dir: Path) -> None:
    path = photos_dir / "Alice" / "2019" / "a.jpg"
    assert photos.library_name(path) == "Alice/2019/a.jpg"
    assert photos.album_of(path) == "Alice"
    assert photos.album_of(photos_dir / "a.jpg") is None


def test_albums_are_the_folders_right_in_the_library(photos_dir: Path) -> None:
    make_photos(
        photos_dir, "a.jpg", "Alice/b.jpg", "Alice/2019/c.jpg", "Alice and Bob/d.jpg"
    )
    found = {
        album: sorted(map(photos.library_name, group))
        for album, group in photos.by_album(photos.scan_photos()).items()
    }
    assert found == {
        None: ["a.jpg"],
        "Alice": ["Alice/2019/c.jpg", "Alice/b.jpg"],
        "Alice and Bob": ["Alice and Bob/d.jpg"],
    }


def test_an_album_is_named_by_the_longest_start() -> None:
    names = ["Alice", "Alice and Bob", None]
    found = photos.album_named("alice  AND bob 2024-06-01", names)
    assert found == ("Alice and Bob", "2024-06-01")
    assert photos.album_named("Alice 2024-06-01", names) == ("Alice", "2024-06-01")
    assert photos.album_named("Alice", names) == ("Alice", "")
    assert photos.album_named("Alicea", names) is None
    assert photos.album_named("2024-06-01", names) is None


def album_round_names() -> list[str]:
    return photos.get_settings().album_rounds_file.read_text().splitlines()


def test_each_album_has_a_round_of_its_own(photos_dir: Path) -> None:
    make_photos(photos_dir, "Alice/a.jpg", "Alice/b.jpg", "Bob/c.jpg", "d.jpg")
    # As 0.99.19 left it, with the albums' rounds in it too
    get_settings().sent_photos_file.write_text("Bob/c.jpg\ngone/e.jpg\n")
    for _ in range(2):
        assert photos.random_photo_message(track_sent=True, album="Alice")
    library = ["Alice/a.jpg", "Alice/b.jpg", "Bob/c.jpg", "gone/e.jpg"]
    assert sorted(sent_names()) == sorted(album_round_names()) == library
    # All of Alice's sent: her round starts over, Bob's as it was, and a
    # photo no longer in the library is forgotten; the library's round, as
    # the daily post's, keeps every photo it has had
    assert photos.random_photo_message(track_sent=True, album="Alice")
    [bob, alice] = album_round_names()
    assert bob == "Bob/c.jpg"
    assert alice in ("Alice/a.jpg", "Alice/b.jpg")
    assert sorted(sent_names()) == library


def test_an_albums_round_never_repeats_the_librarys(photos_dir: Path) -> None:
    library = {"a1.jpg": "A/a1.jpg", "a2.jpg": "A/a2.jpg", "b.jpg": "B/b.jpg"}
    make_photos(photos_dir, *library.values(), "c.jpg")
    library["c.jpg"] = "c.jpg"

    def pick(album: str | None = None) -> str:
        message = photos.random_photo_message(track_sent=True, album=album)
        assert message is not None and message.text
        return library[message.text.rsplit("🖼️ ", 1)[1]]

    # The library's round, as the daily post's, while A's round goes round
    # again and again in between: no photo twice until every one has come
    this_round: set[str] = set()
    for _ in range(30):
        picked = pick()
        if this_round == set(library.values()):
            this_round = set()  # over, so a new one starts
        assert picked not in this_round
        this_round |= {picked, pick("A")}


def test_the_librarys_round_counts_every_albums(photos_dir: Path) -> None:
    make_photos(photos_dir, "a.jpg", "Alice/b.jpg")
    get_settings().sent_photos_file.write_text("Alice/b.jpg\n")
    message = photos.random_photo_message(track_sent=True)
    assert message is not None
    assert message.text == "⚠️ Date unknown (see the file name)\n🖼️ a.jpg"


async def test_photos_from_an_album(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "Alice/a.jpg", "Bob/b.jpg")
    await send("/photo alice")
    await send("/uniquephoto ALICE")
    assert [answer.text for answer in answers] == [
        "⚠️ Date unknown (see the file name)\n🖼️ a.jpg"
    ] * 2
    assert sent_names() == ["Alice/a.jpg"]


async def test_an_album_that_isnt_one(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "Alice/a.jpg")
    for text in ("/photo Carol", "/photo new", "/uniquephoto Carol", "/photo Alice x"):
        await send(text)
    assert [answer.text for answer in answers] == [
        "There's no album Carol: /albums lists them.",
        "/photo new is /uniquephoto now.",
        "There's no album Carol: /albums lists them.",
        photos.photo_usage(),
    ]


async def test_the_photo_taken_nearest_a_moment(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "a.jpg", taken="2024:06:01 14:52:00")
    make_photos(photos_dir, "b.jpg", taken="2024:06:01 15:30:00")
    make_photos(photos_dir, "c.jpg")  # when, unknown
    for moment in ("15:00", "15:30", "16:45"):
        await send(f"/photo 2024-06-01 {moment}")
    assert [answer.text for answer in answers] == [
        "**Nearest to 2024-06-01 15:00: 8 min before**\n\n📅 2024-06-01 14:52",
        # That minute: no heading
        "📅 2024-06-01 15:30",
        "**Nearest to 2024-06-01 16:45: 1 h 15 min before**\n\n📅 2024-06-01 15:30",
    ]


async def test_a_photo_taken_on_a_day(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "a.jpg", taken="2024:06:01 08:00:00")
    make_photos(photos_dir, "b.jpg", taken="2024:06:04 08:00:00")
    for day in ("2024-06-01", "2024-06-03", "2024-05-01"):
        await send(f"/photo {day}")
    assert [answer.text for answer in answers] == [
        "📅 2024-06-01 08:00",
        # Else on the nearest day that has some
        "**Nearest to 2024-06-03: 1 day after**\n\n📅 2024-06-04 08:00",
        "**Nearest to 2024-05-01: 31 days after**\n\n📅 2024-06-01 08:00",
    ]


async def test_a_photo_taken_in_a_year_a_month_or_an_hour(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "a.jpg", taken="2017:05:14 15:10:00")
    make_photos(photos_dir, "b.jpg", taken="2019:01:02 08:00:00")
    for when in ("2017", "2017-05", "2017-05-14 15", "2018", "2017-07", "2017-05-14 9"):
        await send(f"/photo {when}")
    for when in ("2017-13", "2017-05-14 24", "2017-5"):
        await send(f"/photo {when}")
    assert [answer.text for answer in answers] == [
        "📅 2017-05-14 15:10",
        "📅 2017-05-14 15:10",
        "📅 2017-05-14 15:10",
        # Else the nearest of its size that has some, the earlier of two
        "**Nearest to 2018: 1 year before**\n\n📅 2017-05-14 15:10",
        "**Nearest to 2017-07: 2 months before**\n\n📅 2017-05-14 15:10",
        "**Nearest to 2017-05-14 09:00: 6 hours after**\n\n📅 2017-05-14 15:10",
        # No such month, no such hour, and a month by one digit
        *[photos.photo_usage()] * 3,
    ]


async def test_a_photo_by_date_from_an_album(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "Alice/a.jpg", taken="2024:06:01 08:00:00")
    make_photos(photos_dir, "Bob/b.jpg", taken="2024:06:01 08:05:00")
    await send("/photo Alice 2024-06-01 08:05")
    assert [answer.text for answer in answers] == [
        "**Nearest to 2024-06-01 08:05: 5 min before**\n\n📅 2024-06-01 08:00"
    ]


async def test_no_photo_says_when_it_was_taken(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "a.jpg")
    await send("/photo 2024-06-01")
    await send("/photo 2024-02-30")
    assert [answer.text for answer in answers] == [
        "No photo there says when it was taken.",
        photos.photo_usage(),
    ]


@pytest.mark.usefixtures("born")
def test_an_albums_own_birth_date(photos_dir: Path) -> None:
    make_photos(
        photos_dir, "Alice/a.jpg", "Bob/b.jpg", "c.jpg", taken="2020:06:15 12:00:00"
    )
    # By its name in any case
    photos.album_settings.add(photos.AlbumSettings("alice", date(2020, 6, 14)))
    assert caption(photos_dir / "Alice/a.jpg") == "📅 2020-06-15 12:00\n🎂 1 day"
    # An album without one shows no age
    assert caption(photos_dir / "Bob/b.jpg") == "📅 2020-06-15 12:00"
    # Photos in no album, photos_birth_date's
    assert caption(photos_dir / "c.jpg") == "📅 2020-06-15 12:00\n🎂 1 year"


def test_photo_stats_count_the_albums(photos_dir: Path) -> None:
    make_photos(photos_dir, "Alice/a.jpg", "b.jpg")
    assert photos.photo_stats().splitlines()[-1] == "📚 In 1 album"


async def test_the_cache_of_an_album(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "Alice/a.jpg", "Alice/2021/b.jpg", "c.jpg")
    for text in ("/cache alice", "/cache Bob", "/cache"):
        await send(text)
    alice, bob, library = [answer.text or "" for answer in answers]
    assert alice.startswith("📂 Alice has 2 photos (")
    assert alice.splitlines()[1].startswith("JPG: 2 files (")
    assert "📚" not in alice
    assert bob == "There's no album Bob: /albums lists them."
    assert library.startswith("📂 Photo cache contains 3 photos (")
    assert library.endswith("📚 In 1 album")


async def test_a_simple_photo_has_no_text(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "Alice/a.jpg", taken="2024:06:01 14:52:00")
    make_photos(photos_dir, "Bob/b.jpg")
    # As /photo picks it, by album and by date, but the photo alone: no
    # caption, nor a heading saying how near it is
    await send("/sphoto alice")
    await send("/sphoto 2024-06-01 15:00")
    await send("/sphoto bob")
    assert [(answer.text, answer.text_mode) for answer in answers] == [(None, None)] * 3
    assert all(answer.base64_attachments for answer in answers)
    # Nor does it count toward the rounds
    assert not get_settings().sent_photos_file.exists()
    # What isn't a photo is said as /photo says it
    answers.clear()
    await send("/sphoto Carol")
    assert [answer.text for answer in answers] == [
        "There's no album Carol: /albums lists them."
    ]


async def test_photo_message_without_its_caption(
    photos_dir: Path, answers: list[SendMessage]
) -> None:
    make_photos(photos_dir, "a.jpg")
    message = await photos.photo_message("", caption=False)
    assert isinstance(message, SendMessage)
    assert message.text is None and message.base64_attachments
