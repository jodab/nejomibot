"""Photos from the local library, with when and where each was taken, and an
age.

Each folder right in photos_dir is an album, named as the folder, its
subfolders part of it; photos right in photos_dir are in none, but among all
photos. A command names an album in any case, as the longest start of what
follows it, so names may have spaces: /photo Alice and Bob.

/photo picks a photo at random, from every album or from the one named.
With a date, /photo 2024-06-01, it picks one taken that day, or else on the
nearest day that has some; with a time too, /photo Alice 2024-06-01 15:00,
the one taken nearest that moment, in the bot's timezone, as captions have
it. When each photo was taken is read once, from its header, and kept while
the bot runs (moments()), about 400 bytes a photo, so the first /photo with
a date after a start takes longer.

/uniquephoto picks among the photos not sent yet in this round, and counts
toward it: none twice until every photo has been sent, then a new round
starts. Each album has a round of its own: /uniquephoto Alice picks among
Alice's, and once all of hers have been sent, her round starts over, the
others' as they were. A timer that runs /uniquephoto every day posts each
photo once, round after round. /photo and /onthisday don't count toward it.

With a birth date, captions show the age of who's in the photos on the day:
the album's own, which /album sets (albums.py), or else photos_birth_date.

HEIC and HEIF photos are sent as JPEG, with photos_heif; without it they're
left out, which saves the memory of pillow-heif, which opens them.
"""

import asyncio
import base64
import io
import logging
import math
import re
import threading
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from typing import IO, Any

from dateutil.relativedelta import relativedelta
from PIL import ExifTags, Image
from signalbot import DataMessageContext, SendMessage, TextMode

from .commands import Command, Handler, answer, argument
from .config import get_settings
from .files import KeptLines, append_privately, write_privately
from .i18n import _, format_duration, format_file_size, ngettext
from .messages import chance, drawn, error_text, escape, log_failure
from .timers import CLOCK, DATE

logger = logging.getLogger(__name__)

EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".avif", ".webp")
# Not every Signal client shows HEIF, so these are sent as JPEG
HEIF = (".heic", ".heif")
MAX_ATTEMPTS = 5
EXIF_TIME = "%Y:%m:%d %H:%M:%S"
UTC_OFFSET = re.compile(r"^[+-]\d{2}:\d{2}$")
MAX_ZONE_SHIFT = timedelta(hours=14)  # the farthest any time zone is from UTC
# OpenStreetMap's short links: their characters, and the zoom of the map they
# show, which also sets how close the link is, about a metre or two
OSM_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_~"
OSM_ZOOM = 16
REMOVE = "-"  # after /album <album>: no birth date of its own

# /uniquephoto's pick and its marking as sent, one at a time, so two at once
# don't pick the same photo
picking = threading.Lock()

# When each photo was taken, by its path, with its mtime and size when read
taken: dict[str, tuple[int, int, datetime | None]] = {}
reading = threading.Lock()  # one look through the library at a time


@cache
def heif_opener() -> None:
    """Let Pillow open HEIF: imported when first needed, as it takes memory."""
    import pillow_heif

    pillow_heif.register_heif_opener()  # pyright: ignore[reportUnknownMemberType]


def open_image(source: Path | IO[bytes]) -> Image.Image:
    """A picture: a photo from the library, or one sent to the bot."""
    if get_settings().photos_heif:
        heif_opener()
    return Image.open(source)


def extensions() -> tuple[str, ...]:
    return EXTENSIONS + HEIF if get_settings().photos_heif else EXTENSIONS


def scan_photos() -> list[Path]:
    """List all photos in the library. Fast enough to run on every request."""
    wanted = extensions()
    return [
        dirpath / name
        for dirpath, _dirs, names in get_settings().photos_dir.walk()
        for name in names
        if name.lower().endswith(wanted)
    ]


def library_name(path: Path) -> str:
    """The photo's path in the library, as the file of those sent lists it.
    Its start taken off as text, as pathlib's relative_to() takes a hundred
    times as long, which a library of thousands of photos feels."""
    return str(path).removeprefix(f"{str(get_settings().photos_dir).rstrip('/')}/")


# Albums


def album_of(path: Path) -> str | None:
    """The album the photo is in: the folder right in photos_dir it's in, if
    any."""
    album, slash, _rest = library_name(path).partition("/")
    return album if slash else None


def by_album(photos: Iterable[Path]) -> dict[str | None, list[Path]]:
    """The photos of each album; None's are those in none."""
    found: dict[str | None, list[Path]] = {}
    for path in photos:
        found.setdefault(album_of(path), []).append(path)
    return found


def album_named(text: str, names: Iterable[str | None]) -> tuple[str, str] | None:
    """The album whose name is the longest start of the text, in any case,
    and what follows it; None if none's is."""
    words = text.split()
    for name in sorted(filter(None, names), key=lambda name: -len(name.split())):
        wanted = name.casefold().split()
        if wanted and [word.casefold() for word in words[: len(wanted)]] == wanted:
            return name, " ".join(words[len(wanted) :])
    return None


def album_alone(text: str) -> str | None:
    """The album the whole text names, in any case, if one does."""
    found = album_named(text, by_album(scan_photos()))
    return found[0] if found and not found[1] else None


def no_album(name: str) -> str:
    return _("There's no album {name}: /albums lists them.").format(name=name)


# The albums' birth dates, which /album sets


@dataclass(frozen=True)
class BirthDate:
    """The birth date of who's in an album's photos."""

    album: str  # as its folder is named
    day: date


BIRTH_DATES_HEADER = (
    "# nejomibot's albums' birth dates, one per line:",
    "#   album | 2019-06-15",
    "# The album is a folder right in photos_dir, by its name: its photos'",
    "# captions show the age of who's in them, born on that day. An album not",
    "# here takes photos_birth_date, if the config has one.",
    "# Changed with /album in Signal, or by hand: the bot reads it again when",
    "# it changes, and leaves comments and lines it can't read as they are.",
)


def parse_birth_date(line: str) -> BirthDate:
    """A line of the file. Raises ValueError."""
    album, bar, day = line.rpartition("|")
    if not bar or not album.strip():
        raise ValueError("no album")
    return BirthDate(album.strip(), date.fromisoformat(day.strip()))


def birth_date_line(entry: BirthDate) -> str:
    return f"{entry.album} | {entry.day:%Y-%m-%d}"


birth_dates = KeptLines(
    "albums.txt", BIRTH_DATES_HEADER, parse_birth_date, birth_date_line
)


def own_birth_dates(album: str) -> list[BirthDate]:
    """The album's lines in the file: one, but for hand edits."""
    folded = album.casefold()
    return [e for e in birth_dates.current().entries if e.album.casefold() == folded]


def birth_date(album: str | None) -> date | None:
    """The birth date ages count from in the album's photos: its own, the
    last line's if there are more, or else photos_birth_date."""
    if album is not None and (own := own_birth_dates(album)):
        return own[-1].day
    return get_settings().photos_birth_date


# The round


def unsent_photos(photos: list[Path], album: str | None = None) -> list[Path]:
    """The photos not yet sent in this round, of the album's if one is
    named; all of them once every one has been, as a new round starts: the
    library's, or the album's alone, its photos taken off the list of those
    sent, the others' left on it.

    The sent ones are listed in a file, by their paths in the library, one
    per line, so the rounds survive restarts. Photos added later join the
    current round, removed ones are ignored, and the file never lists more
    than the library holds (plus removed photos) before it starts over.
    """
    sent_file = get_settings().sent_photos_file
    try:
        lines = sent_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeError) as e:
        logger.warning("Could not read the list of sent photos: %r", e)
        lines = []
    sent = set(lines)
    if draw := drawn.get():
        # Its run in another language marked it sent: this one picks it too
        sent -= draw.used
    unsent = [path for path in photos if library_name(path) not in sent]
    if unsent:
        logger.info("%d of %d photos not sent yet", len(unsent), len(photos))
        return unsent
    logger.info("All %d photos have been sent, starting over", len(photos))
    try:
        if album is None:
            sent_file.unlink(missing_ok=True)
        else:
            # Its photos off the list, and those no longer in the library
            present = {library_name(path) for path in scan_photos()}
            others = [
                line
                for line in lines
                if line in present and not line.startswith(f"{album}/")
            ]
            write_privately(sent_file, "".join(f"{line}\n" for line in others))
    except OSError as e:
        logger.warning("Could not start the round over: %r", e)
    return photos


def mark_sent(path: Path) -> None:
    """Add the photo to those sent in this round: once, in whichever language
    its command runs first."""
    name = library_name(path)
    if draw := drawn.get():
        if name in draw.used:
            return
        draw.used.add(name)
    try:
        append_privately(get_settings().sent_photos_file, name)
    except OSError as e:
        logger.warning("Could not add %s to the sent photos: %r", path, e)


# Reading a photo


def exif_of(img: Image.Image) -> Image.Exif:
    """The image's EXIF, as its header has it: a PNG's after the image data
    is left out, as reading it would take the whole image."""
    return img.getexif() if "exif" in img.info else Image.Exif()


def read_photo(path: Path) -> Image.Exif | None:
    """The photo's EXIF, or None if it's no image Pillow can read."""
    try:
        with open_image(path) as img:
            exif = exif_of(img)
            img.verify()
    except Exception as e:
        logger.error("Image validation failed for '%s': %s", path, e)
        return None
    return exif


def photo_bytes(path: Path) -> bytes:
    """The file as it is, or converted to JPEG if it is HEIF."""
    if path.suffix.lower() not in HEIF:
        return path.read_bytes()
    logger.warning(
        "Converting %s to JPEG to send it; better convert the library with "
        "tools/tidy-photos.sh",
        path,
    )
    buffer = io.BytesIO()
    with open_image(path) as img:
        # pillow-heif has already turned the image upright
        rgb = img if img.mode == "RGB" else img.convert("RGB")
        rgb.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def exif_time(tags: dict[int, Any], tag: int) -> datetime | None:
    try:
        return datetime.strptime(str(tags[tag]).strip(), EXIF_TIME)
    except KeyError, ValueError:
        return None


def is_zone_shift(difference: timedelta) -> bool:
    """Whether two times this far apart can be one moment written in two time
    zones: a whole number of quarter hours, 14 hours at most."""
    seconds = difference.total_seconds()
    return seconds != 0 and seconds % 900 == 0 and abs(difference) <= MAX_ZONE_SHIFT


def exif_offset(tags: dict[int, Any]) -> str | None:
    """The UTC offset saved with DateTimeOriginal, e.g. '+03:00'."""
    tag = tags.get(ExifTags.Base.OffsetTimeOriginal) or tags.get(
        ExifTags.Base.OffsetTime
    )
    offset = str(tag).strip() if tag else ""
    return offset if UTC_OFFSET.match(offset) else None


def exif_datetime(exif: Image.Exif) -> datetime | None:
    """When the photo was taken, in the bot's time zone. None if unknown.

    DateTimeOriginal is the time on the clock where the photo was taken, in
    the zone of the offset saved with it, or else photos_timezone. But some
    phones save it in UTC and CreateDate in local time, whatever offset they
    give: a CreateDate a time zone away tells, as in tools/tidy-photos.sh.
    """
    settings = get_settings()
    tags = exif.get_ifd(ExifTags.IFD.Exif)
    original = exif_time(tags, ExifTags.Base.DateTimeOriginal)
    created = exif_time(tags, ExifTags.Base.DateTimeDigitized)
    if original is None:
        local = exif_time(dict(exif), ExifTags.Base.DateTime)
        taken = local.replace(tzinfo=settings.photos_tz) if local else None
    elif created is not None and is_zone_shift(created - original):
        taken = original.replace(tzinfo=UTC)
    elif offset := exif_offset(tags):
        taken = datetime.fromisoformat(f"{original.isoformat()}{offset}")
    else:
        taken = original.replace(tzinfo=settings.photos_tz)
    return taken.astimezone(settings.tz) if taken else None


def moment_taken(path: Path) -> datetime | None:
    """When the photo was taken, as its caption has it; None if that's not
    known, or it's no image Pillow can read. Only its header is read."""
    try:
        with open_image(path) as img:
            exif = exif_of(img)
    except Exception as e:
        logger.warning("Could not read when %s was taken: %s", path, e)
        return None
    return exif_datetime(exif)


def moments(photos: list[Path]) -> dict[Path, datetime]:
    """When each photo of the library, as scan_photos() lists it, was taken,
    if known. Photos read before and unchanged since aren't read again; those
    gone are forgotten. Blocking."""
    found: dict[Path, datetime] = {}
    with reading:
        seen: dict[str, tuple[int, int, datetime | None]] = {}
        for path in photos:
            try:
                stat = path.stat()
            except OSError:
                continue
            known = taken.get(name := str(path))
            if known and known[:2] == (stat.st_mtime_ns, stat.st_size):
                moment = known[2]
            else:
                moment = moment_taken(path)
            seen[name] = (stat.st_mtime_ns, stat.st_size, moment)
            if moment:
                found[path] = moment
        taken.clear()
        taken.update(seen)
    return found


def exif_location(exif: Image.Exif) -> tuple[float, float] | None:
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    try:
        lat = to_degrees(gps[ExifTags.GPS.GPSLatitude])
        lon = to_degrees(gps[ExifTags.GPS.GPSLongitude])
        if gps[ExifTags.GPS.GPSLatitudeRef] != "N":
            lat = -lat
        if gps[ExifTags.GPS.GPSLongitudeRef] != "E":
            lon = -lon
    except KeyError:
        return None
    except Exception as e:
        logger.error("Invalid GPS data: %s", e)
        return None
    if not lat or not lon or not math.isfinite(lat + lon):
        return None
    return lat, lon


def to_degrees(value: Any) -> float:
    d, m, s = (float(part) for part in value[:3])
    return d + m / 60.0 + s / 3600.0


def osm_code(lat: float, lon: float, zoom: int) -> str:
    """OpenStreetMap's short code for a place, as in https://osm.org/go/<code>:
    the bits of the longitude and the latitude, interleaved, 6 to a character
    from OSM_DIGITS, as many as the zoom wants, and a - for each zoom level
    short of the next character's."""
    x = int((lon + 180) * 2**32 / 360) & 0xFFFFFFFF
    y = int((lat + 90) * 2**32 / 180) & 0xFFFFFFFF
    bits = 0
    for i in range(31, -1, -1):
        bits = (bits << 2) | ((x >> i) & 1) << 1 | ((y >> i) & 1)
    digits = -(-(zoom + 8) // 3)
    code = "".join(OSM_DIGITS[(bits >> (58 - 6 * i)) & 0x3F] for i in range(digits))
    return code + "-" * ((zoom + 8) % 3)


def map_link(lat: float, lon: float) -> str:
    """Where the photo was taken, on the map photos_map says."""
    if get_settings().photos_map == "openstreetmap":
        # m shows a marker there
        return f"https://osm.org/go/{osm_code(lat, lon, OSM_ZOOM)}?m="
    return f"https://maps.google.com/maps?q={lat:.5f},{lon:.5f}"


# The caption


def format_age(taken: datetime, born: date | None) -> str:
    """The age on the day, in the bot's time zone, of who was born on born,
    if given: e.g. '🎂 9 years, 2 months and 3 days'."""
    day = taken.date()
    if born is None or day < born:
        return ""
    diff = relativedelta(day, born)
    parts = [
        text.format(n=n)
        for n, text in (
            (diff.years, ngettext("{n} year", "{n} years", diff.years)),
            (diff.months, ngettext("{n} month", "{n} months", diff.months)),
            (diff.days, ngettext("{n} day", "{n} days", diff.days)),
        )
        if n > 0
    ]
    if not parts:
        return ""
    age = parts[0]
    if len(parts) > 1:
        age = _("{list} and {last}").format(list=", ".join(parts[:-1]), last=parts[-1])
    return f"{get_settings().photos_age_emoji} {age}"


def photo_caption(path: Path, exif: Image.Exif, heading: str = "") -> str:
    """When and where the photo was taken, under the heading, in bold, if
    any. Styled."""
    meta_parts: list[str] = []

    taken = exif_datetime(exif)
    if taken:
        meta_parts.append(f"📅 {taken:%Y-%m-%d %H:%M}")
        if age := format_age(taken, birth_date(album_of(path))):
            meta_parts.append(age)
    else:
        meta_parts.append(_("⚠️ Date unknown (see the file name)"))
        meta_parts.append(f"🖼️ {path.name}")

    if location := exif_location(exif):
        meta_parts.append(f"\n{map_link(*location)}")

    metadata = escape("\n".join(meta_parts))
    return f"**{escape(heading)}**\n\n{metadata}" if heading else metadata


# Picking one


def random_photo_message(
    heading: str = "", *, track_sent: bool = False, album: str | None = None
) -> SendMessage | None:
    """Pick a random valid photo, of the album's if one is named, and build
    its message. Blocking.

    With track_sent (/uniquephoto), only photos not sent yet in this round
    are picked, and the pick is added to the sent ones.
    """
    photos = scan_photos()
    if album is not None:
        photos = [path for path in photos if album_of(path) == album]
    if not photos:
        logger.warning("No photos found in %s", get_settings().photos_dir)
        return None
    if not track_sent:
        return pick(photos, heading)
    with picking:
        return pick(unsent_photos(photos, album), heading, track_sent=True)


def pick(
    candidates: list[Path], heading: str, *, track_sent: bool = False
) -> SendMessage | None:
    tries = chance().sample(candidates, min(MAX_ATTEMPTS, len(candidates)))
    for attempt, path in enumerate(tries, start=1):
        logger.info("Attempt %d: %s", attempt, path)
        if track_sent:
            # Marked before sending, and also when broken, so every round ends
            mark_sent(path)
        if (exif := read_photo(path)) is None:
            continue
        try:
            attachment = base64.b64encode(photo_bytes(path)).decode()
            caption = photo_caption(path, exif, heading)
        except Exception:
            logger.exception("Error preparing '%s'", path)
            continue
        return SendMessage(
            text=caption, base64_attachments=[attachment], text_mode=TextMode.STYLED
        )
    return None


def nearest_moment(wanted: datetime, found: dict[Path, datetime]) -> SendMessage | None:
    """The photo taken nearest the moment, under how far off it is, unless
    it's that minute; None if no photo's time is known. Blocking."""
    if not found:
        return None
    path = min(found, key=lambda path: (abs(found[path] - wanted), found[path]))
    off = found[path] - wanted
    heading = ""
    if abs(off) >= timedelta(minutes=1):
        if off > timedelta():
            text = _("Nearest to {moment}: {off} after")
        else:
            text = _("Nearest to {moment}: {off} before")
        heading = text.format(
            moment=f"{wanted:%Y-%m-%d %H:%M}", off=format_duration(abs(off))
        )
    return pick([path], heading)


def nearest_day(wanted: date, found: dict[Path, datetime]) -> SendMessage | None:
    """A photo taken on the day, at random, or else on the nearest day that
    has some, under how far off that is; None if no photo's day is known.
    Blocking."""
    days: dict[date, list[Path]] = {}
    for path, moment in found.items():
        days.setdefault(moment.date(), []).append(path)
    if not days:
        return None
    day = min(days, key=lambda day: (abs((day - wanted).days), day))
    heading = ""
    if off := (day - wanted).days:
        if off > 0:
            text = ngettext(
                "Nearest to {day}: {count} day after",
                "Nearest to {day}: {count} days after",
                off,
            )
        else:
            text = ngettext(
                "Nearest to {day}: {count} day before",
                "Nearest to {day}: {count} days before",
                -off,
            )
        heading = text.format(day=f"{wanted:%Y-%m-%d}", count=abs(off))
    candidates = days[day]
    for path in chance().sample(candidates, min(MAX_ATTEMPTS, len(candidates))):
        if message := pick([path], heading):
            return message
    return None


def photo_usage() -> str:
    return _(
        "/photo [<album>] [<date> [<time>]]: a random photo, from every album "
        "or the one named, or the one taken nearest a moment, e.g. /photo "
        "2024-06-01 15:00. /albums lists the albums."
    )


def when_wanted(text: str) -> tuple[date, time | None] | None:
    """The day, and the time if given, of 2024-06-01 or 2024-06-01 15:00;
    None if it's neither."""
    match text.split():
        case [day] if DATE.match(day):
            at = None
        case [day, clock] if DATE.match(day) and (found := CLOCK.match(clock)):
            at = time(int(found[1]), int(found[2]))
        case _:
            return None
    try:
        return date.fromisoformat(day), at
    except ValueError:
        return None


def photo_for(text: str) -> SendMessage | str:
    """What /photo answers what follows it with: a photo, or what to say
    instead. Blocking."""
    library = scan_photos()
    groups = by_album(library)
    album, rest = None, text
    if found := album_named(text, groups):
        album, rest = found
    if not rest:
        return random_photo_message(album=album) or no_photo()
    if (wanted := when_wanted(rest)) is None:
        if album is None and not re.match(r"^\d", rest):
            if rest.casefold() == "new":
                return _("/photo new is /uniquephoto now.")
            return no_album(rest)
        return photo_usage()
    found_at = moments(library)
    if album is not None:
        found_at = {path: found_at[path] for path in groups[album] if path in found_at}
    day, at = wanted
    if at is None:
        message = nearest_day(day, found_at)
    else:
        message = nearest_moment(datetime.combine(day, at, get_settings().tz), found_at)
    return message or _("No photo there says when it was taken.")


def unique_photo_for(text: str) -> SendMessage | str:
    """What /uniquephoto answers what follows it with. Blocking."""
    album = None
    if text and (album := album_alone(text)) is None:
        return no_album(text)
    return random_photo_message(track_sent=True, album=album) or no_photo()


def no_photo() -> str:
    logger.error("Found no valid photo in %d attempts", MAX_ATTEMPTS)
    return error_text(_("found no photo that could be sent"))


async def photo_message(text: str = "", *, unique: bool = False) -> SendMessage | str:
    """The photo that /photo, or /uniquephoto, followed by text asks for, or
    what to say instead, as what went wrong."""
    try:
        return await asyncio.to_thread(unique_photo_for if unique else photo_for, text)
    except Exception as e:
        log_failure(logger, "Picking a photo", e)
        return error_text(e)


# The library's size


def photo_stats(album: str | None = None) -> str:
    """How many photos the library has, or the album, and how big they are,
    by type; and how many albums the library has. Blocking."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    library = scan_photos()
    photos = library if album is None else by_album(library).get(album, [])
    for path in photos:
        ext = path.suffix.lower()
        counts[ext] += 1
        sizes[ext] += path.stat().st_size

    total = counts.total()
    size = format_file_size(sizes.total())
    if album is None:
        heading = ngettext(
            "📂 Photo cache contains {count} photo ({size}):",
            "📂 Photo cache contains {count} photos ({size}):",
            total,
        ).format(count=total, size=size)
    else:
        heading = ngettext(
            "📂 {album} has {count} photo ({size}):",
            "📂 {album} has {count} photos ({size}):",
            total,
        ).format(album=album, count=total, size=size)
    lines = [heading]
    lines += [
        ngettext(
            "{type}: {count} file ({size})", "{type}: {count} files ({size})", count
        ).format(
            type=ext.lstrip(".").upper(),
            count=count,
            size=format_file_size(sizes[ext]),
        )
        for ext, count in sorted(counts.items())
    ]
    if album is None and (albums := len(by_album(photos).keys() - {None})):
        lines.append(
            ngettext("📚 In {count} album", "📚 In {count} albums", albums).format(
                count=albums
            )
        )
    return "\n".join(lines)


def cache_for(text: str) -> str:
    """What /cache answers what follows it with: the library's photos, or
    the album's. Blocking."""
    album = None
    if text and (album := album_alone(text)) is None:
        return no_album(text)
    return photo_stats(album)


async def cache_message(text: str = "") -> str:
    """How many photos there are, in the library or in the album the text
    names, and their size, or what to say instead, as what went wrong."""
    try:
        return await asyncio.to_thread(cache_for, text)
    except Exception as e:
        log_failure(logger, "Counting the photos", e)
        return error_text(e)


class Photo(Handler):
    commands = (
        Command("/photo", more=True),
        Command("/uniquephoto", more=True),
        Command("/cache", more=True),
    )

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = argument(context.message.text)
        if command.name == "/cache":
            await answer(context, lambda: cache_message(text))
            return
        unique = command.name == "/uniquephoto"
        await answer(context, lambda: photo_message(text, unique=unique), slow=True)
