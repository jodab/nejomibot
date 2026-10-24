#!/usr/bin/env bash
# tidy-photos.sh - tidy up a folder of photos for nejomibot.
#
# For every photo in DIR and its subfolders (hidden folders are skipped):
#
#  1. HEIC/HEIF photos are converted to JPG, because not every Signal client
#     can show HEIC. Date, GPS, camera and colour data are kept, and the HEIC
#     file is removed once its JPG has been written.
#  2. Photos are renamed after the moment they were taken, from the EXIF tags
#     DateTimeOriginal and SubSecTimeOriginal:
#         20240606_185711.575.JPG        (YYYYMMDD_HHMMSS.mmm)
#     If DateTimeOriginal was saved in UTC (CreateDate is then a time zone
#     off: whole quarter hours, 14 hours at most), CreateDate is used, so
#     names are always in local time.
#     The extension always matches the real file format, in uppercase.
#     Photos without an EXIF date keep their name; only the extension is fixed.
#  3. When several photos would get the same name, you choose the one to keep
#     (the others are deleted), or keep them all as NAME_1.JPG, NAME_2.JPG...
#     Byte-identical copies are pointed out.
#
# Nothing is changed until every question is answered and you confirm the plan.
# Running it again on a tidy folder changes nothing. TIFF and BMP files are
# renamed too, but the bot sends only JPEG, PNG, GIF, WebP, AVIF and HEIC.
#
# Usage: tidy-photos.sh [options] [DIR]      (DIR defaults to .)
#
#   -n, --dry-run   show what would be done; change nothing, ask nothing
#   -y, --yes       don't ask: delete byte-identical copies, skip the other
#                   conflicts, and apply the plan
#   -q, --quiet     don't list every change, only questions, problems, totals
#   -h, --help      show this help
#
# Needs exiftool, and ImageMagick (magick) when there are HEIC files.

set -euo pipefail

# EXIF times carry no time zone. Treating them as UTC everywhere means turning
# them into seconds and back can never shift them (no daylight saving gaps).
export TZ=UTC

# ---- Settings ---------------------------------------------------------------

# Uppercase extension for each file format (as exiftool names it) that counts
# as a photo. Files in any other format, like videos, are left alone.
declare -A EXTENSION=(
  [JPEG]=.JPG [PNG]=.PNG [GIF]=.GIF [WEBP]=.WEBP [AVIF]=.AVIF [TIFF]=.TIF [BMP]=.BMP
  [HEIC]=.JPG [HEIF]=.JPG # converted, see CONVERT
)

# Formats that are converted to JPG with to_jpg.
declare -A CONVERT=([HEIC]=1 [HEIF]=1)

JPEG_QUALITY=92            # quality of the converted JPGs, 1-100
VIEWER=${VIEWER:-xdg-open} # program the "v" answer opens photos with

# Convert photo $1 to the JPG file $2. ImageMagick applies the HEIC rotation,
# copies the metadata and resets the EXIF orientation, so photos don't end up
# rotated twice.
JPG_TOOL=magick # the program to_jpg needs, checked before anything is changed
to_jpg() {
  magick "$1" -quality "$JPEG_QUALITY" "$2"
}

# ---- State ------------------------------------------------------------------

dry_run=0 assume_yes=0 quiet=0 dir=.

# Every file found gets a number; these arrays are indexed by it.
path=()   # where the file is now
format=() # file format from exiftool: JPEG, HEIC, ... ("-" if unknown)
taken=()  # capture time as YYYYMMDD_HHMMSS.mmm, "" without an EXIF date
size=()   # in bytes                    \
dims=()   # width x height               } shown when asking about conflicts
camera=() # camera model and software   /
target=() # the path it gets, "" if it stays where it is
action=() # rename, convert, delete, or "" for nothing

declare -A number_of=() # path -> file number
declare -A wanted_by=() # new path -> numbers of the files that get it, "3 17 "
conflicts=()            # new paths that more than one file would get

photos=0 undated=0 skipped=0 from_utc=0       # counted while planning
renames=0 converts=0 deletes=0                # planned changes
renamed=0 converted=0 deleted=0 failed=0      # what actually happened
converting=""                                 # JPG being written, see convert_file
trap 'if [[ -n $converting ]]; then rm -f -- "$converting"; fi' EXIT

# ---- Output -----------------------------------------------------------------

info() { printf '%s\n' "$*"; }
detail() { if ((!quiet)); then printf '%s\n' "$*"; fi; } # hidden by --quiet
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# Print the help text: the comment block at the top of this file.
usage() {
  sed -n '2,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
}

# Format a number of bytes for people, like exiftool does: 2.8 MB, 674 kB.
human_size() {
  local b=$1
  if ((b >= 1000000)); then
    printf '%d.%d MB' $((b / 1000000)) $((b % 1000000 / 100000))
  elif ((b >= 1000)); then
    printf '%d kB' $((b / 1000))
  else
    printf '%d B' "$b"
  fi
}

# Ask question $1 and put the answer, lowercased, in $answer. An empty answer
# means default $2. With --yes the default is taken without asking.
ask() {
  if ((assume_yes)); then
    answer=$2
    info "$1 $2 (--yes)"
    return
  fi
  printf '%s [%s] ' "$1" "$2"
  if ! IFS= read -r answer; then
    printf '\n'
    die "No answer (input closed); nothing has been changed."
  fi
  answer=${answer// /}
  answer=${answer:-$2}
  answer=${answer,,}
}

# ---- Steps, in the order main runs them -------------------------------------

parse_args() {
  while (($#)); do
    case $1 in
      -n | --dry-run) dry_run=1 ;;
      -y | --yes) assume_yes=1 ;;
      -q | --quiet) quiet=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      --)
        shift
        break
        ;;
      -*) die "Unknown option: $1 (see --help)" ;;
      *) break ;;
    esac
    shift
  done
  (($# <= 1)) || die "Give at most one folder (see --help)."
  dir=${1:-.}
  [[ -d $dir ]] || die "Not a folder: $dir"
  if [[ $dir != / ]]; then dir=${dir%/}; fi
  if [[ $dir == -* ]]; then dir=./$dir; fi # so exiftool doesn't take it as an option
  command -v exiftool >/dev/null || die "exiftool is not installed (Arch: perl-image-exiftool)."
}

# Remember a file: add_file PATH FORMAT TAKEN SIZE DIMS CAMERA
add_file() {
  local n=${#path[@]}
  path[n]=$1 format[n]=$2 taken[n]=$3 size[n]=$4 dims[n]=$5 camera[n]=$6
  target[n]="" action[n]=""
  number_of[$1]=$n
}

# True if two EXIF times $1 seconds apart are the same moment written in two
# time zones: a whole number of quarter hours, 14 hours at most. Many Samsung,
# Pixel and Nexus photos (and some others) save DateTimeOriginal in UTC but
# CreateDate in local time; their GPS time confirms it.
is_zone_shift() {
  local diff=$1
  ((diff != 0 && diff % 900 == 0 && diff >= -14 * 3600 && diff <= 14 * 3600))
}

# Read the metadata of every file below $dir with one exiftool run.
# -fast2 skips parts of the files that aren't needed, which is ~30% quicker.
# Dates come as seconds (-d %s) so they can be compared.
scan() {
  local out d name fmt original created subsec bytes wh model software when
  info "Reading the photos in $dir ..."
  if ! out=$(exiftool -q -fast2 -r -T -d %s \
    -Directory -FileName -FileType -EXIF:DateTimeOriginal -EXIF:CreateDate \
    -EXIF:SubSecTimeOriginal -FileSize# -ImageSize -Model -Software "$dir"); then
    warn "exiftool reported errors (see above); going on with the files it could read."
  fi

  # -T prints tab-separated columns, with "-" for missing values. read would
  # merge neighbouring tabs around an empty value, so split on \x1f instead.
  # Sorting lists the changes by folder and name later on.
  out=$(LC_ALL=C sort <<<"${out//$'\t'/$'\x1f'}")
  while IFS=$'\x1f' read -r d name fmt original created subsec bytes wh model software; do
    [[ -n $name ]] || continue
    when="" # stays empty without a date, or with one like 0000:00:00 00:00:00
    if [[ $original =~ ^[0-9]+$ ]]; then
      if [[ $created =~ ^[0-9]+$ ]] && is_zone_shift $((created - original)); then
        original=$created
        ((++from_utc))
      fi
      # SubSecTimeOriginal holds fractions of a second ("84" is 0.84 s):
      # pad and cut it to milliseconds
      subsec=${subsec//[^0-9]/}000
      printf -v when '%(%Y%m%d_%H%M%S)T.%s' "$original" "${subsec:0:3}"
    fi
    if [[ $wh == - ]]; then wh=""; fi
    if [[ $model == - ]]; then model=""; fi
    if [[ $software != - ]]; then model+=" $software"; fi
    bytes=${bytes//[^0-9]/}
    add_file "$d/$name" "${fmt:--}" "$when" "${bytes:-0}" "$wh" "$model"
  done <<<"$out"
}

# Work out the new name of every photo.
plan() {
  local n name ext stem new
  for n in "${!path[@]}"; do
    ext=${EXTENSION[${format[n]}]-}
    [[ -n $ext ]] || continue # not a photo: leave it alone
    ((++photos))
    name=${path[n]##*/}

    if [[ -n ${taken[n]} ]]; then
      stem=${taken[n]}
      # NAME_1.JPG, NAME_2.JPG... are duplicates kept on an earlier run
      if [[ -z ${CONVERT[${format[n]}]-} && $name =~ ^"$stem"_[0-9]+"$ext"$ ]]; then
        continue
      fi
    else
      ((++undated))
      stem=${name%.*}
    fi

    new=${path[n]%/*}/$stem$ext
    if [[ -n ${CONVERT[${format[n]}]-} ]]; then
      action[n]=convert
    elif [[ $new != "${path[n]}" ]]; then
      action[n]=rename
    else
      continue # already has the right name
    fi
    target[n]=$new
    wanted_by[$new]+="$n "
  done
}

# True if file $1 is the same file as one of the files numbered $2...
# (-ef also catches a.jpg and a.JPG on filesystems that ignore case.)
same_as_any() {
  local file=$1 n
  shift
  for n; do
    if [[ $file -ef ${path[n]} ]]; then return 0; fi
  done
  return 1
}

# Find the new names that more than one file would get. A file that already
# has the name, and keeps it, is one of them. A file that has the name but is
# renamed itself is no problem: it moves out of the way first.
find_conflicts() {
  local new here members
  for new in "${!wanted_by[@]}"; do
    # shellcheck disable=SC2086 # the numbers are meant to be split
    if [[ -e $new ]] && ! same_as_any "$new" ${wanted_by[$new]}; then
      here=${number_of[$new]-}
      if [[ -z $here ]]; then # a file exiftool couldn't read
        add_file "$new" - "" "$(stat -c %s -- "$new")" "" ""
        here=${number_of[$new]}
      fi
      if [[ -z ${action[here]} ]]; then wanted_by[$new]+="$here "; fi
    fi
    read -ra members <<<"${wanted_by[$new]}"
    if ((${#members[@]} > 1)); then conflicts+=("$new"); fi
  done
  if ((${#conflicts[@]})); then
    mapfile -t conflicts < <(printf '%s\n' "${conflicts[@]}" | sort)
  fi
}

# Stop early if there are HEIC files and nothing to convert them with.
check_jpg_tool() {
  local n
  for n in "${!action[@]}"; do
    if [[ ${action[n]} == convert ]]; then
      command -v "$JPG_TOOL" >/dev/null ||
        die "$JPG_TOOL (ImageMagick) is needed to convert HEIC photos to JPG."
      return 0
    fi
  done
}

# Ask what to do about each conflict. Only the plan changes here; files are
# touched after the final confirmation.
resolve_conflicts() {
  local i=0 new
  ((${#conflicts[@]})) || return 0
  info ""
  info "${#conflicts[@]} new name(s) would be given to more than one file."
  if ((!dry_run && !assume_yes)); then
    info "For each, answer with:"
    info "  1, 2, ...  keep that file and delete the others"
    info "  a          keep them all, numbered NAME_1, NAME_2, ..."
    info "  v          open them in $VIEWER to compare"
    info "  s          skip: leave these files as they are for now"
    info "  q          quit without changing anything"
  fi
  for new in "${conflicts[@]}"; do
    ((++i))
    resolve_conflict "$new" "[$i/${#conflicts[@]}]"
  done
}

# List the files that would get name $1 and ask which one to keep.
# $2 is a label like [3/12].
resolve_conflict() {
  local new=$1 label=$2 n j k count note same all_same=1 here=0 default=s
  local -a files

  # largest first: usually the original, or the best quality
  # shellcheck disable=SC2086 # the numbers are meant to be split
  mapfile -t files < <(for n in ${wanted_by[$new]}; do
    printf '%s %s\n' "${size[n]}" "$n"
  done | sort -rn | cut -d' ' -f2)
  count=${#files[@]}

  info ""
  info "$label $count files would be named ${new##*/} (in ${new%/*}):"
  for k in "${!files[@]}"; do
    n=${files[k]}
    note=""
    if [[ ${path[n]} == "$new" ]]; then
      note=" (has this name now)"
      here=$((k + 1))
    fi
    same=-1
    for ((j = 0; j < k; j++)); do
      if cmp -s -- "${path[files[j]]}" "${path[n]}"; then
        same=$j
        note+=" (same as $((j + 1)))"
        break
      fi
    done
    if ((k > 0 && same != 0)); then all_same=0; fi
    printf '  %d) %8s  %-5s %-10s %-24.24s  %s%s\n' $((k + 1)) \
      "$(human_size "${size[n]}")" "${format[n]}" "${dims[n]:-?}" \
      "${camera[n]:--}" "${path[n]##*/}" "$note"
  done
  if ((all_same)); then
    info "  All $count files are identical."
    default=$((here ? here : 1))
  fi

  if ((dry_run)); then
    skip_files "${files[@]}"
    return
  fi
  while true; do
    ask "  Keep which (1-$count/a/v/s/q)?" "$default"
    case $answer in
      q)
        info "Stopped; nothing has been changed."
        exit 1
        ;;
      s)
        skip_files "${files[@]}"
        return
        ;;
      a)
        keep_all "$new" "${files[@]}"
        return
        ;;
      v) view "${files[@]}" ;;
      *)
        if [[ $answer =~ ^[0-9]+$ ]] && ((10#$answer >= 1 && 10#$answer <= count)); then
          keep_one "${files[10#$answer - 1]}" "${files[@]}"
          return
        fi
        info "  Please answer with a number from 1 to $count, or a, v, s or q."
        ;;
    esac
  done
}

# Plan for file $1 to get the new name and the others ($2...) to be deleted.
keep_one() {
  local keep=$1 n
  shift
  for n; do
    if ((n != keep)); then action[n]=delete target[n]=""; fi
  done
}

# Keep all files ($2...) that would get name $1. The one that has the name
# now, or else the first, gets it; the others get NAME_1, NAME_2, ...
keep_all() {
  local new=$1 first=$2 base=${1%.*} ext=.${1##*.} n i=1 name
  shift
  for n; do
    if [[ ${path[n]} == "$new" ]]; then first=$n; fi
  done
  for n; do
    ((n != first)) || continue
    name=${base}_$i$ext
    while [[ -e $name || -n ${wanted_by[$name]-} ]]; do
      ((++i))
      name=${base}_$i$ext
    done
    target[n]=$name
    wanted_by[$name]+="$n "
  done
}

# Leave the files numbered $1... as they are.
skip_files() {
  local n
  for n; do action[n]="" target[n]=""; done
  ((++skipped))
}

# Open the files numbered $1... in the image viewer, in the background.
view() {
  local n
  if ! command -v "$VIEWER" >/dev/null; then
    info "  $VIEWER is not installed; set VIEWER to your image viewer."
    return
  fi
  for n; do "$VIEWER" "${path[n]}" >/dev/null 2>&1 & done
}

# List the planned changes (unless --quiet) and print the totals.
show_plan() {
  local n
  info ""
  for n in "${!path[@]}"; do
    case ${action[n]} in
      rename)
        ((++renames))
        detail "rename   ${path[n]}  ->  ${target[n]##*/}"
        ;;
      convert)
        ((++converts))
        detail "convert  ${path[n]}  ->  ${target[n]##*/}"
        ;;
      delete)
        ((++deletes))
        detail "delete   ${path[n]}"
        ;;
      *)
        if [[ -n ${EXTENSION[${format[n]}]-} && -z ${taken[n]} ]]; then
          detail "no date  ${path[n]}  (left as it is)"
        fi
        ;;
    esac
  done

  info ""
  info "$photos photos in $dir:"
  total "$renames" "to rename"
  total "$converts" "to convert to JPG (the HEIC files are removed)"
  total "$deletes" "to delete"
  total "$undated" "without an EXIF date (name kept, extension fixed)"
  total "$from_utc" "with DateTimeOriginal in UTC (named after CreateDate)"
  if ((dry_run)); then
    total "$skipped" "conflict(s) to decide on (you'll be asked when it runs for real)"
  else
    total "$skipped" "conflict(s) skipped (those files stay as they are)"
  fi
}

# Print one line of the totals, unless the count is 0.
total() {
  if (($1)); then printf '  %6d %s\n' "$1" "$2"; fi
}

# Stop here on a dry run, when there's nothing to do, or if the user says no.
confirm() {
  local changes=$((renames + converts + deletes))
  if ((changes == 0)); then
    info "Nothing to change."
    exit 0
  fi
  if ((dry_run)); then
    info "Dry run: nothing has been changed."
    exit 0
  fi
  ((!assume_yes)) || return 0
  ask "Apply these $changes changes (y/n)?" n
  if [[ $answer != y* ]]; then
    info "Nothing has been changed."
    exit 1
  fi
}

# Rename $1 to $2 without ever overwriting a file. (mv -n reports success
# even when it skips, so check that the file really moved.)
move() {
  mv -n -- "$1" "$2" && [[ ! -e $1 || $1 -ef $2 ]]
}

# Convert photo number $1 to JPG at its new name, then remove the original.
# The JPG is written to a hidden temporary file first, so a failed or
# interrupted conversion leaves no half-written photo behind.
convert_file() {
  local n=$1 src=${path[$1]} dst=${target[$1]}
  converting=${dst%/*}/.converting-$$.JPG
  if to_jpg "$src" "$converting" && [[ -s $converting ]] &&
    touch -r "$src" -- "$converting"; then # keep the file date
    if [[ $dst -ef $src ]]; then
      # a HEIC that was already called .JPG: replace it
      if mv -f -- "$converting" "$dst"; then
        converting=""
        ((++converted))
        return
      fi
    elif move "$converting" "$dst"; then
      converting=""
      rm -- "$src" || warn "Converted, but could not remove $src"
      ((++converted))
      return
    fi
  fi
  rm -f -- "$converting"
  converting=""
  warn "Could not convert $src"
  ((++failed))
}

# Carry out the plan: deletions first, as they free names up, then the
# renames and conversions.
apply_plan() {
  local n
  local -a pending=() waiting=()
  for n in "${!path[@]}"; do
    case ${action[n]} in
      delete)
        if rm -- "${path[n]}"; then ((++deleted)); else ((++failed)); fi
        ;;
      rename | convert) pending+=("$n") ;;
    esac
  done

  # A new name can still be taken by a file that is renamed itself (A -> B
  # while B -> C). Such files wait for the next round; stop when a round gets
  # nothing done.
  while ((${#pending[@]})); do
    waiting=()
    for n in "${pending[@]}"; do
      if [[ -e ${target[n]} && ! ${target[n]} -ef ${path[n]} ]]; then
        waiting+=("$n")
      elif [[ ${action[n]} == convert ]]; then
        convert_file "$n"
      elif move "${path[n]}" "${target[n]}"; then
        ((++renamed))
      else
        warn "Could not rename ${path[n]}"
        ((++failed))
      fi
    done
    ((${#waiting[@]} < ${#pending[@]})) || break
    pending=("${waiting[@]}")
  done
  for n in "${waiting[@]}"; do
    warn "Left alone, ${target[n]##*/} is taken: ${path[n]}"
    ((++failed))
  done
}

report() {
  info "Done: $renamed renamed, $converted converted, $deleted deleted."
  if ((failed)); then
    warn "$failed file(s) could not be changed, see above."
    exit 1
  fi
}

main() {
  parse_args "$@"
  scan
  plan
  find_conflicts
  check_jpg_tool
  resolve_conflicts
  show_plan
  confirm
  apply_plan
  report
}

main "$@"
