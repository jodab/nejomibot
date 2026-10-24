#!/usr/bin/env bash
# translations.sh - bring the translations up to date with the bot's messages.
#
# Usage: translations.sh [LANGUAGE]
#
# Collects the messages marked for translation in nejomibot/*.py (see
# nejomibot/i18n.py) into nejomibot/locale/messages.pot, the template that
# translation tools such as Poedit and Weblate start a language from, and
# merges them into each nejomibot/locale/*.po: a new message comes in
# untranslated, a changed one marked fuzzy, and one that's gone goes.
# Untranslated and fuzzy messages show in English until they're translated,
# and the tests fail on them.
#
# With LANGUAGE, a code such as de or pt_BR, it starts a new language first:
# LANGUAGE.po from the template, and LANGUAGE.toml, for its names for the
# commands and the words it reads in them, from template.toml.
#
# Needs GNU gettext: xgettext, msgmerge, msgattrib, msgfmt and msginit.

set -euo pipefail

cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.."
locale=nejomibot/locale
template=$(mktemp --suffix=.pot)
trap 'rm -f -- "$template"' EXIT

xgettext --language=Python --from-code=UTF-8 \
  --keyword=_ --keyword=N_ --keyword=ngettext:1,2 \
  --add-location=file --sort-by-file --package-name=nejomibot \
  --output=- nejomibot/*.py | {
  # In place of xgettext's placeholder title and copyright lines
  printf '%s\n' "# nejomibot's messages, the template for each language's .po:" \
    "# tools/translations.sh writes it from the code."
  tail -n +3
} >"$template"
# Only when the messages change, so its date alone changes nothing
if ! diff -q -I '^"POT-Creation-Date: ' "$template" "$locale/messages.pot" >/dev/null 2>&1; then
  cp --no-preserve=mode -- "$template" "$locale/messages.pot"
fi

if (($# > 0)); then
  if [[ ! -f $locale/$1.po ]]; then
    msginit --no-translator --locale="$1" --input="$locale/messages.pot" \
      --output-file="$locale/$1.po"
  fi
  if [[ ! -f $locale/$1.toml ]]; then
    cp -- "$locale/template.toml" "$locale/$1.toml"
    echo "$locale/$1.toml: give the language's own name and its names"
  fi
fi

for po in "$locale"/*.po; do
  msgmerge --quiet --add-location=file --output-file="$po" "$po" "$locale/messages.pot"
  msgattrib --no-obsolete --output-file="$po" "$po" # what the code no longer has
  echo "$po: $(msgfmt --statistics --output-file=/dev/null "$po" 2>&1)"
done
