"""Photos from the local library, with when and where each was taken, and an
age.

Each folder right in photos_dir is an album, named as the folder, its
subfolders part of it; photos right in photos_dir are in none, but among all
photos. A command names an album in any case, as the longest start of what
follows it, so names may have spaces: /photo Alice and Bob.

/photo picks a photo at random, from every album or from the one named;
/sphoto, a simple photo, picks as /photo does, and sends the photo alone,
without its caption or heading.
With a date, as exact as it's given, it picks one taken then: in 2017, in
2017-05, on 2017-05-14 or at 15 that day, as /photo 2017-05-14 15, or else
in the nearest year, month, day or hour that has some; to the minute, as
/photo Alice 2024-06-01 15:00, the one taken nearest that moment, in the
bot's timezone, as captions have it. When each photo was taken is read
from its header in the background once the bot has started (index()), and
kept while it runs (moments()), about 400 bytes a photo; a photo added or
changed later is read when one of these commands next needs it.

/uniquephoto picks among the photos not sent yet in this round, and counts
toward it: none twice until every photo has been sent, then a new round
starts. Each album has a round of its own: /uniquephoto Alice picks among
Alice's, and once all of hers have been sent, her round starts over. A photo
sent in either round counts in both, and a round that starts over leaves the
others as they are, so none sends a photo twice in its round. A timer that
runs /uniquephoto every day posts each photo once, round after round.
/photo and /onthisday don't count toward the rounds.

With a birth date, captions show the age of who's in the photos on the day:
the album's own, which /album sets (albums.py); an album has none until it's
set. Photos in no album take photos_birth_date.
An album can have shortcuts, too, other names for /photo with it, as /alice
for /photo Alice.

HEIC and HEIF photos are sent as JPEG, with photos_heif; without it they're
left out, which saves the memory of pillow-heif, which opens them.
"""

import asyncio
import base64
import contextlib
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
from signalbot import DataMessageContext, SendMessage, SignalBot, TextMode

from .commands import Command, Handler, answer, argument, built_in
from .config import as_command, get_settings
from .files import KeptLines, append_privately, write_privately
from .i18n import _, format_duration, format_file_size, ngettext
from .messages import chance, drawn, error_text, escape, log_failure
from .timers import CLOCK, DATE

logger = logging.getLogger(__name__)

EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".avif", ".webp")
# Not every Signal client shows HEIF, so these are sent as JPEG
HEIF = (".heic", ".heif")
MAX_ATTEMPTS = 5
INDEX_CHUNK = 100  # photos read at a time in the background (index())
EXIF_TIME = "%Y:%m:%d %H:%M:%S"
UTC_OFFSET = re.compile(r"^[+-]\d{2}:\d{2}$")
MAX_ZONE_SHIFT = timedelta(hours=14)  # the farthest any time zone is from UTC
# OpenStreetMap's short links: their characters, and the zoom of the map they
# show, which also sets how close the link is, about a metre or two
OSM_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_~"
OSM_ZOOM = 16
REMOVE = "-"  # after /album <album>, or its or a special's shortcuts: none

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
    """List all photos in the library, as Path.walk() does: a folder's own,
    then each of its folders' in turn, without following links to folders.
    Fast enough to run on every request: iterdir()'s paths keep their
    directory entry's text, so str(), which library_name() and moments()
    need, costs nothing, while it took 140 ms for 7,641 photos on a
    Raspberry Pi 4 when joined from walk()'s names."""
    wanted = extensions()
    found: list[Path] = []
    folders = [get_settings().photos_dir]
    while folders:
        try:
            paths = list(folders.pop().iterdir())
        except OSError:
            continue  # skipped, as walk() does
        subfolders: list[Path] = []
        for path in paths:
            if path.info.is_dir(follow_symlinks=False):
                subfolders.append(path)
            elif str(path).lower().endswith(wanted):
                found.append(path)
        folders.extend(reversed(subfolders))  # so they're read in order
    return found


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


def album_alone(text: str, library: list[Path]) -> str | None:
    """The album of the library that the whole text names, in any case, if
    one does."""
    found = album_named(text, by_album(library))
    return found[0] if found and not found[1] else None


def no_album(name: str) -> str:
    return _("There's no album {name}: /albums lists them.").format(name=name)


# What albums have of their own, which /album sets


@dataclass(frozen=True)
class AlbumSettings:
    """What an album has of its own: the birth date of who's in its photos,
    and shortcuts, other names for /photo with the album."""

    album: str  # as its folder is named
    born: date | None = None
    shortcuts: tuple[str, ...] = ()  # each a word with a / first (as_command)


ALBUMS_HEADER = (
    "# nejomibot's albums, one per line:",
    "#   album | 2019-06-15 | /alice /al",
    "# The album is a folder right in photos_dir, by its name. Its photos'",
    "# captions show the age of who's in them, born on that day. Each",
    "# shortcut, a word that starts with /, is another name for /photo with",
    "# the album: /alice is /photo Alice, and /alice 2024 /photo Alice 2024.",
    "# Either may be left out.",
    "# Changed with /album in Signal, or by hand: the bot reads it again when",
    "# it changes, and leaves comments and lines it can't read as they are.",
)


def parse_album_settings(line: str) -> AlbumSettings:
    """A line of the file; one without shortcuts may end at the date. A
    shortcut without its / is read with one, as as_command() has it. Raises
    ValueError."""
    album, born, *names = (part.strip() for part in line.rsplit("|", 2))
    shortcuts = tuple(dict.fromkeys(map(as_command, names[0].split()))) if names else ()
    if not album:
        raise ValueError("no album")
    if commands := [name for name in shortcuts if built_in(name)]:
        raise ValueError(f"{commands[0]} is a command")  # which it would hide
    if not born and not shortcuts:
        raise ValueError("neither a birth date nor shortcuts")
    return AlbumSettings(album, date.fromisoformat(born) if born else None, shortcuts)


def album_settings_line(entry: AlbumSettings) -> str:
    born = f"{entry.born:%Y-%m-%d}" if entry.born else ""
    return f"{entry.album} | {born} | {' '.join(entry.shortcuts)}".rstrip()


album_settings = KeptLines(
    "albums.txt", ALBUMS_HEADER, parse_album_settings, album_settings_line
)


def album_lines(album: str) -> list[AlbumSettings]:
    """The album's lines in the file: one, but for hand edits."""
    folded = album.casefold()
    return [
        entry
        for entry in album_settings.current().entries
        if entry.album.casefold() == folded
    ]


def own_settings(album: str) -> AlbumSettings:
    """What the album has of its own: its last line's, or nothing."""
    found = album_lines(album)
    return found[-1] if found else AlbumSettings(album)


def birth_date(album: str | None) -> date | None:
    """The birth date ages count from in the album's photos: its own, if
    set; for photos in no album, photos_birth_date."""
    if album is None:
        return get_settings().photos_birth_date
    return own_settings(album).born


# The rounds


def sent_lines(path: Path) -> list[str]:
    """The photos a round's file lists, by their paths in the library; none
    if it isn't there, or can't be read."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError) as e:
        logger.warning("Could not read %s: %r", path.name, e)
        return []


def keep_album_rounds(lines: list[str]) -> None:
    """Make album-rounds.txt list the lines. Raises OSError."""
    path = get_settings().album_rounds_file
    write_privately(path, "".join(f"{line}\n" for line in lines))


def album_rounds() -> list[str]:
    """The photos sent in their albums' rounds, as album-rounds.txt lists
    them. Before 0.99.20, sent-photos.txt kept them with the library's, so
    the file starts as what that has of albums."""
    settings = get_settings()
    if settings.album_rounds_file.exists():
        return sent_lines(settings.album_rounds_file)
    lines = [line for line in sent_lines(settings.sent_photos_file) if "/" in line]
    try:
        keep_album_rounds(lines)
    except OSError as e:
        logger.warning("Could not write %s: %r", settings.album_rounds_file.name, e)
    return lines


def unsent_photos(
    photos: list[Path], album: str | None = None, library: list[Path] | None = None
) -> list[Path]:
    """The photos not sent yet in this round: the library's, or with an
    album, the album's, of the library given or listed now; all of them once
    every one has been, as its new round starts.

    Each round is listed in a file, by the photos' paths in the library, a
    line each, so the rounds survive restarts: the library's in
    sent-photos.txt, the albums' in album-rounds.txt. A photo sent in either
    counts in both, so neither sends it again in its round, and a round that
    starts over leaves the others as they are. Photos added later join the
    current rounds, and removed ones are ignored.
    """
    albums = album_rounds()
    lines = sent_lines(get_settings().sent_photos_file) if album is None else albums
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
            get_settings().sent_photos_file.unlink(missing_ok=True)
        else:
            # Its photos off the list, and those no longer in the library
            listed = scan_photos() if library is None else library
            present = {library_name(path) for path in listed}
            keep_album_rounds(
                [
                    line
                    for line in albums
                    if line in present and not line.startswith(f"{album}/")
                ]
            )
    except OSError as e:
        logger.warning("Could not start the round over: %r", e)
    return photos


def mark_sent(path: Path) -> None:
    """Add the photo to those sent in its rounds, the library's and its
    album's: once, in whichever language its command runs first."""
    name = library_name(path)
    if draw := drawn.get():
        if name in draw.used:
            return
        draw.used.add(name)
    settings = get_settings()
    rounds = [settings.sent_photos_file]
    if album_of(path) is not None:
        rounds.append(settings.album_rounds_file)
    for kept in rounds:
        try:
            if name not in sent_lines(kept):
                append_privately(kept, name)
        except OSError as e:
            logger.warning("Could not add %s to %s: %r", name, kept.name, e)


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


def entry_for(path: Path) -> tuple[int, int, datetime | None] | None:
    """The photo's mtime and size, and when it was taken: as read before if
    it hasn't changed since, else read now. None if it's gone. With reading
    held."""
    try:
        stat = path.stat()
    except OSError:
        return None
    known = taken.get(str(path))
    if known and known[:2] == (stat.st_mtime_ns, stat.st_size):
        return known
    return stat.st_mtime_ns, stat.st_size, moment_taken(path)


def moments(photos: list[Path]) -> dict[Path, datetime]:
    """When each photo of the library, as scan_photos() lists it, was taken,
    if known. Photos read before and unchanged since aren't read again; those
    gone are forgotten. Blocking."""
    found: dict[Path, datetime] = {}
    with reading:
        seen: dict[str, tuple[int, int, datetime | None]] = {}
        for path in photos:
            if (entry := entry_for(path)) is None:
                continue
            seen[str(path)] = entry
            if entry[2]:
                found[path] = entry[2]
        taken.clear()
        taken.update(seen)
    return found


def remember(photos: list[Path]) -> None:
    """Read when these photos were taken, those new or changed since, for
    moments(), which keeps the rest. Blocking."""
    with reading:
        for path in photos:
            if entry := entry_for(path):
                taken[str(path)] = entry


async def index() -> None:
    """Read when each photo was taken, once the bot has started, so that the
    first /photo with a date, /albums or /onthisday needn't. A chunk at a
    time, so a command can go first, and a stop waits for one chunk at most.
    Photos added or changed later are read by the next of those commands,
    and those removed are forgotten."""
    logger.info("Reading when the photos were taken")
    clock = asyncio.get_running_loop()
    began = clock.time()
    try:
        library = await asyncio.to_thread(scan_photos)
        for start in range(0, len(library), INDEX_CHUNK):
            await asyncio.to_thread(remember, library[start : start + INDEX_CHUNK])
    except Exception as e:
        log_failure(logger, "Reading when the photos were taken", e)
        return
    logger.info(
        "Read when %d photos were taken, in %.1f s", len(library), clock.time() - began
    )


def start(bot: SignalBot) -> None:
    """Read when the photos were taken, in the background, once signalbot is
    ready."""
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        index, id="photo-index", misfire_grace_time=None, replace_existing=True
    )


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
    heading: str = "",
    *,
    track_sent: bool = False,
    album: str | None = None,
    library: list[Path] | None = None,
) -> SendMessage | None:
    """Pick a random valid photo, of the album's if one is named, from the
    library given or listed now, and build its message. Blocking.

    With track_sent (/uniquephoto), only photos not sent yet in this round
    are picked, and the pick is added to the sent ones.
    """
    library = scan_photos() if library is None else library
    photos = library
    if album is not None:
        photos = [path for path in library if album_of(path) == album]
    if not photos:
        logger.warning("No photos found in %s", get_settings().photos_dir)
        return None
    with picking if track_sent else contextlib.nullcontext():
        candidates = unsent_photos(photos, album, library) if track_sent else photos
        message = pick(candidates, heading, track_sent=track_sent)
    if message is None:
        tries = min(MAX_ATTEMPTS, len(candidates))
        logger.error("Found no valid photo in %d attempts", tries)
    return message


def pick(
    candidates: list[Path], heading: str, *, track_sent: bool = False
) -> SendMessage | None:
    tries = chance().sample(candidates, min(MAX_ATTEMPTS, len(candidates)))
    for attempt, path in enumerate(tries, start=1):
        # The path at DEBUG: an album is often named after someone
        logger.debug("Attempt %d: %s", attempt, path)
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


def nearest_heading(asked: str, off: str, after: bool) -> str:
    """E.g. 'Nearest to 2017-05-14: 3 days after'."""
    if after:
        return _("Nearest to {moment}: {off} after").format(moment=asked, off=off)
    return _("Nearest to {moment}: {off} before").format(moment=asked, off=off)


def nearest_moment(wanted: datetime, found: dict[Path, datetime]) -> SendMessage | None:
    """The photo taken nearest the moment, under how far off it is, unless
    it's that minute, or if it can't be read, the next nearest; None if no
    photo's time is known. Blocking."""
    nearest = sorted(found, key=lambda path: (abs(found[path] - wanted), found[path]))
    for path in nearest[:MAX_ATTEMPTS]:
        off = found[path] - wanted
        heading = ""
        if abs(off) >= timedelta(minutes=1):
            asked = f"{wanted:%Y-%m-%d %H:%M}"
            off_text = format_duration(abs(off))
            heading = nearest_heading(asked, off_text, off > timedelta())
        if message := pick([path], heading):
            return message
    return None


# How exactly /photo's date says when: a year, a month, a day or an hour,
# from which it picks a photo at random; to the minute, a moment, nearest
# which it picks one
YEAR, MONTH, DAY, HOUR = range(4)
PERIOD_NAMES = ("%Y", "%Y-%m", "%Y-%m-%d", "%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class Period:
    """A year, month, day or hour that /photo asks for, by when it starts."""

    start: datetime  # in the bot's time zone
    size: int  # YEAR, MONTH, DAY or HOUR

    def of(self, moment: datetime) -> int:
        """Which period of this size the moment is in, counted from year 0."""
        if self.size == YEAR:
            return moment.year
        if self.size == MONTH:
            return moment.year * 12 + moment.month - 1
        days = moment.date().toordinal()
        return days if self.size == DAY else days * 24 + moment.hour

    def counted(self, count: int) -> str:
        """So many periods of this size, e.g. '3 years'."""
        if self.size == YEAR:
            text = ngettext("{n} year", "{n} years", count)
        elif self.size == MONTH:
            text = ngettext("{n} month", "{n} months", count)
        elif self.size == DAY:
            text = ngettext("{n} day", "{n} days", count)
        else:
            text = ngettext("{n} hour", "{n} hours", count)
        return text.format(n=count)


def nearest_period(period: Period, found: dict[Path, datetime]) -> SendMessage | None:
    """A photo taken in the period, at random, or else in the nearest one
    of its size that has some, under how far off that is; None if no
    photo's time is known. Blocking."""
    periods: dict[int, list[Path]] = {}
    for path, moment in found.items():
        periods.setdefault(period.of(moment), []).append(path)
    if not periods:
        return None
    wanted = period.of(period.start)
    nearest = min(periods, key=lambda each: (abs(each - wanted), each))
    heading = ""
    if off := nearest - wanted:
        asked = f"{period.start:{PERIOD_NAMES[period.size]}}"
        heading = nearest_heading(asked, period.counted(abs(off)), off > 0)
    candidates = periods[nearest]
    for path in chance().sample(candidates, min(MAX_ATTEMPTS, len(candidates))):
        if message := pick([path], heading):
            return message
    return None


def photo_usage() -> str:
    return _(
        "/photo [<album>] [<date>]: a random photo, from every album or the one "
        "named; with a date, one taken then, as exactly as you like: 2017, "
        "2017-05, 2017-05-14 or 2017-05-14 15, or the one taken nearest "
        "2017-05-14 15:30. /albums lists the albums."
    )


def when_wanted(text: str) -> Period | datetime | None:
    """When /photo's text asks for: a year, a month, a day or an hour, as
    2017, 2017-05, 2017-05-14 or 2017-05-14 15, or a moment, as 2017-05-14
    15:30; None if it's none of those, or no such time."""
    tz = get_settings().tz
    try:
        match text.split():
            case [year] if re.fullmatch(r"\d{4}", year):
                return Period(datetime(int(year), 1, 1, tzinfo=tz), YEAR)
            case [month] if found := re.fullmatch(r"(\d{4})-(\d{2})", month):
                return Period(
                    datetime(int(found[1]), int(found[2]), 1, tzinfo=tz), MONTH
                )
            case [day] if DATE.match(day):
                return Period(
                    datetime.combine(date.fromisoformat(day), time(), tz), DAY
                )
            case [day, hour] if DATE.match(day) and re.fullmatch(r"\d{1,2}", hour):
                at = time(int(hour))
                return Period(datetime.combine(date.fromisoformat(day), at, tz), HOUR)
            case [day, clock] if DATE.match(day) and (found := CLOCK.match(clock)):
                at = time(int(found[1]), int(found[2]))
                return datetime.combine(date.fromisoformat(day), at, tz)
            case _:
                return None
    except ValueError:  # no such month, day or hour
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
        return random_photo_message(album=album, library=library) or no_photo()
    if (wanted := when_wanted(rest)) is None:
        if album is None and not re.match(r"^\d", rest):
            if rest.casefold() == "new":
                return _("/photo new is /uniquephoto now.")
            return no_album(rest)
        return photo_usage()
    found_at = moments(library)
    if album is not None:
        found_at = {path: found_at[path] for path in groups[album] if path in found_at}
    if isinstance(wanted, Period):
        message = nearest_period(wanted, found_at)
    else:
        message = nearest_moment(wanted, found_at)
    return message or _("No photo there says when it was taken.")


def unique_photo_for(text: str) -> SendMessage | str:
    """What /uniquephoto answers what follows it with. Blocking."""
    library = scan_photos()
    album = None
    if text and (album := album_alone(text, library)) is None:
        return no_album(text)
    message = random_photo_message(track_sent=True, album=album, library=library)
    return message or no_photo()


def no_photo() -> str:
    return error_text(_("found no photo that could be sent"))


async def photo_message(
    text: str = "", *, unique: bool = False, caption: bool = True
) -> SendMessage | str:
    """The photo that /photo, or /uniquephoto, followed by text asks for, or
    what to say instead, as what went wrong; without caption, as /sphoto
    has it, the photo alone, without its caption or heading."""
    try:
        found = await asyncio.to_thread(unique_photo_for if unique else photo_for, text)
    except Exception as e:
        log_failure(logger, "Picking a photo", e)
        return error_text(e)
    if not caption and isinstance(found, SendMessage):
        return found.model_copy(update={"text": None, "text_mode": None})
    return found


# The library's size


def photo_stats(album: str | None = None, library: list[Path] | None = None) -> str:
    """How many photos the library has, as given or listed now, or the
    album, and how big they are, by type; and how many albums the library
    has. Blocking."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    library = scan_photos() if library is None else library
    photos = library if album is None else by_album(library).get(album, [])
    for path in photos:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue  # gone since the scan
        ext = path.suffix.lower()
        counts[ext] += 1
        sizes[ext] += size

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
    library = scan_photos()
    album = None
    if text and (album := album_alone(text, library)) is None:
        return no_album(text)
    return photo_stats(album, library)


async def cache_message(text: str = "") -> str:
    """How many photos there are, in the library or in the album the text
    names, and their size, or what to say instead, as what went wrong."""
    try:
        return await asyncio.to_thread(cache_for, text)
    except Exception as e:
        log_failure(logger, "Counting the photos", e)
        return error_text(e)


class Photo(Handler):
    everyday = True
    commands = (
        Command("/photo", more=True),
        Command("/sphoto", more=True),
        Command("/uniquephoto", more=True),
        Command("/cache", more=True),
    )

    @classmethod
    def shortcuts(cls) -> dict[str, str]:
        """The albums' shortcuts, each for /photo with its album."""
        return {
            name.casefold(): f"/photo {entry.album}"
            for entry in album_settings.current().entries
            for name in entry.shortcuts
        }

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = argument(context.message.text)
        if command.name == "/cache":
            await answer(context, lambda: cache_message(text))
            return
        unique = command.name == "/uniquephoto"
        caption = command.name != "/sphoto"
        await answer(
            context,
            lambda: photo_message(text, unique=unique, caption=caption),
            slow=True,
        )
