"""Compiles the translations: a .mo beside each .po in nejomibot/locale, or in
the folder given, which the bot reads in place of the .po. The image's build
and the release's wheel run it, with polib from the lock:

    uv run --locked --only-group translations tools/compile-translations.py

A checkout needs none: the bot reads the .po files there, through polib.
"""

import sys
from pathlib import Path

import polib

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "nejomibot/locale")
for po in folder.glob("*.po"):
    polib.pofile(str(po)).save_as_mofile(str(po.with_suffix(".mo")))
