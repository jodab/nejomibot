"""Random photo from the local library, with its date, age and location.

HEIC and HEIF photos are sent as JPEG, with photos_heif; without it they're
left out, which saves the memory of pillow-heif, which opens them.
"""

import asyncio
import base64
import io
import logging
import math
import random
import re
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import IO, Any

from dateutil.relativedelta import relativedelta
from PIL import ExifTags, Image
from signalbot import DataMessageContext, SendMessage

from .commands import Command, Handler, answer
from .config import get_settings
from .files import append_privately
from .i18n import _, format_file_size, ngettext
from .messages import error_text, log_failure

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

# The daily post's pick and its marking as sent, one post at a time, so two
# at once don't pick the same photo
picking = threading.Lock()


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
    return [
        dirpath / name
        for dirpath, _dirs, names in get_settings().photos_dir.walk()
        for name in names
        if name.lower().endswith(extensions())
    ]


def library_name(path: Path) -> str:
    return path.relative_to(get_settings().photos_dir).as_posix()


def unsent_photos(photos: list[Path]) -> list[Path]:
    """The photos not yet sent in this round; all of them once every one has been.

    The sent ones are listed in a file, one per line, so the round survives
    restarts. Photos added later join the current round, removed ones are
    ignored, and the file never lists more than the library holds (plus
    removed photos) before it starts over.
    """
    sent_file = get_settings().sent_photos_file
    try:
        sent = set(sent_file.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        sent = set[str]()
    except (OSError, UnicodeError) as e:
        logger.warning("Could not read the list of sent photos: %r", e)
        sent = set[str]()
    unsent = [path for path in photos if library_name(path) not in sent]
    if unsent:
        logger.info("%d of %d photos not sent yet", len(unsent), len(photos))
        return unsent
    logger.info("All %d photos have been sent, starting over", len(photos))
    sent_file.unlink(missing_ok=True)
    return photos


def mark_sent(path: Path) -> None:
    try:
        append_privately(get_settings().sent_photos_file, library_name(path))
    except OSError as e:
        logger.warning("Could not add %s to the sent photos: %r", path, e)


def read_photo(path: Path) -> Image.Exif | None:
    """The photo's EXIF, or None if it's no image Pillow can read. EXIF is
    read with the header, so a PNG's after the image data is left out, as
    reading it would take the whole image."""
    try:
        with open_image(path) as img:
            exif = img.getexif() if "exif" in img.info else Image.Exif()
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


def format_age(taken: datetime) -> str:
    """The age of who's in the photos on the day, in the bot's time zone, if
    their birth date is set: e.g. '🎂 9 years, 2 months and 3 days'."""
    settings = get_settings()
    born = settings.photos_birth_date
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
    return f"{settings.photos_age_emoji} {age}"


def photo_caption(path: Path, exif: Image.Exif, custom_message: str = "") -> str:
    meta_parts: list[str] = []

    taken = exif_datetime(exif)
    if taken:
        meta_parts.append(f"📅 {taken:%Y-%m-%d %H:%M}")
        if age := format_age(taken):
            meta_parts.append(age)
    else:
        meta_parts.append(_("⚠️ Date unknown (see the file name)"))
        meta_parts.append(f"🖼️ {path.name}")

    if location := exif_location(exif):
        meta_parts.append(f"\n{map_link(*location)}")

    metadata = "\n".join(meta_parts)
    return f"{custom_message}\n\n{metadata}" if custom_message else metadata


def random_photo_message(
    custom_message: str = "", *, track_sent: bool = False
) -> SendMessage | None:
    """Pick a random valid photo and build its message. Blocking.

    With track_sent (the daily post), only photos not sent yet in this round
    are picked, and the pick is added to the sent ones.
    """
    photos = scan_photos()
    if not photos:
        logger.warning("No photos found in %s", get_settings().photos_dir)
        return None
    if not track_sent:
        return pick(photos, custom_message)
    with picking:
        return pick(unsent_photos(photos), custom_message, track_sent=True)


def pick(
    candidates: list[Path], custom_message: str, *, track_sent: bool = False
) -> SendMessage | None:
    tries = random.sample(candidates, min(MAX_ATTEMPTS, len(candidates)))
    for attempt, path in enumerate(tries, start=1):
        logger.info("Attempt %d: %s", attempt, path)
        if track_sent:
            # Marked before sending, and also when broken, so every round ends
            mark_sent(path)
        if (exif := read_photo(path)) is None:
            continue
        try:
            attachment = base64.b64encode(photo_bytes(path)).decode()
            caption = photo_caption(path, exif, custom_message)
        except Exception:
            logger.exception("Error preparing '%s'", path)
            continue
        return SendMessage(text=caption, base64_attachments=[attachment])
    return None


async def photo_message(
    custom_message: str = "", *, track_sent: bool = False
) -> SendMessage:
    """A random photo with its caption, or the error to post instead."""
    try:
        message = await asyncio.to_thread(
            random_photo_message, custom_message, track_sent=track_sent
        )
    except Exception as e:
        log_failure(logger, "Picking a photo", e)
        return SendMessage(text=error_text(e))
    if message is None:
        logger.error("Found no valid photo in %d attempts", MAX_ATTEMPTS)
        return SendMessage(text=error_text(_("found no photo that could be sent")))
    return message


def photo_stats() -> str:
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for path in scan_photos():
        ext = path.suffix.lower()
        counts[ext] += 1
        sizes[ext] += path.stat().st_size

    total = counts.total()
    lines = [
        ngettext(
            "📂 Photo cache contains {count} photo ({size}):",
            "📂 Photo cache contains {count} photos ({size}):",
            total,
        ).format(count=total, size=format_file_size(sizes.total()))
    ]
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
    return "\n".join(lines)


async def cache_message() -> str:
    """How many photos there are and their size, or what went wrong."""
    try:
        return await asyncio.to_thread(photo_stats)
    except Exception as e:
        log_failure(logger, "Counting the photos", e)
        return error_text(e)


class Photo(Handler):
    commands = (Command("/photo"), Command("/cache"))

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        if command.name == "/cache":
            await answer(context, cache_message)
        else:
            await answer(context, photo_message, slow=True)
