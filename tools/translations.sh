#!/usr/bin/env bash
# translations.sh - bring the translations up to date with the bot's messages.
#
# Usage: translations.sh [LANGUAGE]
#
# Collects the messages marked for translation in nejomibot/*.py (see
# nejomibot/i18n.py) and merges them into each nejomibot/locale/*.po: a new
# message comes in untranslated, a changed one marked fuzzy, and one that's
# gone goes. Untranslated and fuzzy messages show in English until they're
# translated, and the tests fail on them.
#
# With LANGUAGE, such as de, it starts nejomibot/locale/LANGUAGE.po first, if
# there's none. Its names for commands, and the words it reads in commands,
# go in LANGUAGE.toml: copy sv.toml.
#
# Needs GNU gettext: xgettext, msgmerge, msgattrib and msginit.

set -euo pipefail

cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.."
locale=nejomibot/locale
template=$(mktemp --suffix=.pot)
trap 'rm -f -- "$template"' EXIT

xgettext --language=Python --from-code=UTF-8 \
  --keyword=_ --keyword=N_ --keyword=ngettext:1,2 \
  --add-location=file --sort-by-file --package-name=nejomibot \
  --output="$template" nejomibot/*.py

if (($# > 0)) && [[ ! -f $locale/$1.po ]]; then
  msginit --no-translator --locale="$1" --input="$template" --output-file="$locale/$1.po"
fi

for po in "$locale"/*.po; do
  msgmerge --quiet --update --backup=none --add-location=file "$po" "$template"
  msgattrib --no-obsolete --output-file="$po" "$po" # what the code no longer has
  echo "$po: $(msgfmt --statistics --output-file=/dev/null "$po" 2>&1)"
done
