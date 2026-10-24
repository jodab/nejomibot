#!/usr/bin/env bash
# signal-account.sh - set up and look after a Signal account in signal-cli-rest-api.
#
# Everything signal-cli-rest-api can do with the account itself: register a
# number or link to a phone, the profile (name, About, avatar), username, PIN,
# privacy, linked devices, safety numbers and rate limits. It only talks to the
# REST API, one request at a time, explains what Signal answers, and asks
# before anything that can't be undone.
#
# Usage: signal-account.sh [options] [COMMAND [ARGS...]]
#
# Setting up
#   setup                      guided: register or link, then the profile,
#                              username, PIN and privacy, each one skippable
#   register [--voice] [--captcha LINK]
#                              have Signal send a verification code by SMS, or
#                              call with it (--voice); walks through a captcha
#                              if Signal wants one, then asks for the code,
#                              and has it sent again if none comes
#   verify CODE [--pin]        finish registering with the code; --pin asks for
#                              the PIN of a number with a registration lock
#   link [NAME]                make signal-cli a linked device of a phone,
#                              called NAME there (default nejomibot): shows a
#                              QR code to scan, and waits for it. Not for the
#                              bot: see LINKED below
#
# The account
#   status                     the account and the REST API (the default)
#   profile                    show the profile
#   profile [--name NAME] [--about TEXT | --no-about]
#           [--avatar FILE | --no-avatar]
#                              change it; whatever isn't given stays as it is.
#                              --avatar - takes the picture from standard
#                              input (see In the bot's container, below)
#   username [NAME | --remove] show, set or remove the username; Signal adds a
#                              number to NAME unless it has one, like name.42
#   pin [--remove]             set the registration lock PIN (asked for, so it
#                              stays out of the shell history), or remove it
#   privacy [--number-seen-by everyone|nobody]
#           [--findable-by-number everyone|nobody]
#                              who sees the phone number, and who can find the
#                              account by it
#   rate-limit TOKEN [CAPTCHA] lift a rate limit by solving a captcha, for
#                              the challenge TOKEN Signal gave with it
#   rate-limit --to WHO        send WHO (a phone number) a short test message;
#                              if Signal rate-limits the account, it gives a
#                              challenge, and the captcha comes next. The bot
#                              logs when Signal rate-limits it, but signalbot
#                              doesn't pass the challenge on.
#   unregister [--delete-account] [--delete-local-data]
#                              stop using the number in signal-cli; with
#                              --delete-account, delete the Signal account too
#   delete-local-data [--even-if-registered]
#                              delete what signal-cli keeps of an account that
#                              is no longer registered or linked
#
# Devices
#   devices                    list the linked devices
#   devices add LINK           link another device to this account, with the
#                              sgnl://linkdevice?... link in its QR code
#   devices remove ID          unlink a device
#   devices sync               send the contact list to the linked devices
#
# Safety numbers
#   identities                 everyone's safety number, and whether verified
#   trust WHO SAFETY_NUMBER    verify WHO's safety number (60 digits), once
#                              compared with the one on their phone, as the
#                              bot's /trust does
#   trust WHO --unverified     accept WHO's keys as they are, without verifying
#                              them: after a safety number changed, signal-cli
#                              sends to them again, but they aren't verified
#                              (WHO is a phone number or ID, as identities shows)
#
# The REST API
#   accounts                   the accounts registered in signal-cli
#   search NUMBER...           which phone numbers are on Signal
#   about                      its version and mode
#   log-level [debug|info|warn]
#                              show or set how much it logs
#   trust-mode [always|on-first-use|never]
#                              show or set when new safety numbers are trusted
#                              (in json-rpc mode, only the container sets it)
#
# Options, before or after the command
#   -u, --url URL              signal-cli-rest-api; default: signal_service in
#                              the bot's config, else 127.0.0.1:8080
#   -a, --account NUMBER       the account; default: account in the bot's
#                              config, else the only one registered
#   -c, --config FILE          the bot's config; default: $NEJOMIBOT_CONFIG
#                              (/data/config.toml in the bot's container), else
#                              config.toml beside tools/
#   -y, --yes                  don't ask, not even before what can't be undone
#   -n, --dry-run              show the request that would change something,
#                              and stop there
#   -j, --json                 print what the API answers, as JSON
#   -v, --verbose              show every request (PINs and captchas hidden)
#   -h, --help                 show this help
#
# Examples
#   signal-account.sh                                  # status
#   signal-account.sh setup
#   signal-account.sh profile --about "Weather and photos" --avatar logo.png
#   signal-account.sh username mybot
#
# In the bot's container
#   The image includes the tool, which takes signal-cli-rest-api's address
#   and the account from the bot's settings:
#     podman exec -it nejomibot signal-account.sh setup
#   Without a running bot, in a container of its own on signal-cli-rest-api's
#   network (127.0.0.1:8080; setup asks for the number):
#     podman run --rm -it --no-healthcheck --network container:signal \
#       docker.io/jodab/nejomibot signal-account.sh setup
#   With Compose: docker compose exec nejomibot ..., or without a running bot,
#   docker compose run --rm nejomibot ...
#   An avatar comes from standard input, with --avatar - and -i (not -it):
#     podman exec -i nejomibot signal-account.sh profile --avatar - < logo.png
#   Without a terminal, questions stop the tool; --yes answers them.
#
# Needs curl and jq. qrencode shows link's QR code in the terminal (else it is
# saved as a PNG). Avatars are made square like the bot's /avatar makes them,
# by ImageMagick (magick) or else the bot's own Python, as in its container.
# xdg-open opens the captcha page.
#
# signal-cli-rest-api can't set the family name or the emoji before About: a
# family name stays after a new --name.
#
# LINKED: the bot needs a number of its own, registered. Linked to a phone,
# what its owner types in a direct chat reaches the bot as if the other
# person sent it (signalbot can't tell them apart), so a command typed there
# acts as theirs, and an admin's commands as the admin's.

set -euo pipefail

# ---- Settings ---------------------------------------------------------------

DEFAULT_SERVICE=127.0.0.1:8080 # signal-cli-rest-api's own default port
DEFAULT_DEVICE=nejomibot        # how a linked signal-cli shows on the phone
TIMEOUT=30                      # seconds for most requests
SLOW_TIMEOUT=120                # for those that wait on Signal's servers
LINK_WAIT=180                   # seconds to wait for the QR code to be scanned

# Signal's limits: a name as the Android app cuts it, About as the apps let it
# be typed, what an encrypted profile field holds, and avatars as the Android
# app makes them and the biggest it fetches
NAME_MAX_BYTES=128
ABOUT_MAX_CHARACTERS=140
ABOUT_MAX_BYTES=512
AVATAR_SIDE=1024
AVATAR_MAX_BYTES=$((10 * 1024 * 1024))

PHONE_NUMBER='^\+[1-9][0-9]{6,14}$'
SIGNAL_ID='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
# A nickname, and maybe the number Signal adds to it: mybot, or mybot.42
USERNAME='^[A-Za-z_][A-Za-z0-9_]{2,31}(\.[0-9]{2,9})?$'
REGISTRATION_CAPTCHA=https://signalcaptchas.org/registration/generate.html
CHALLENGE_CAPTCHA=https://signalcaptchas.org/challenge/generate.html

# ---- State ------------------------------------------------------------------

url="" account="" config_file=""
assume_yes=0 dry_run=0 json=0 verbose=0
account_path=""                 # the account, encoded for URLs
accounts=()                     # the accounts in signal-cli, from list_accounts
status=""                       # HTTP status of the last answer
api_version="" api_mode=""      # from read_about
answer="" secret="" captcha=""  # what ask, ask_secret and get_captcha got

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
reply=$work/reply   # body of the last answer
body=$work/body     # body of the next request, from json

# ---- Output -----------------------------------------------------------------

info() { printf '%s\n' "$*"; }
detail() { if ((verbose)); then printf '%s\n' "$*" >&2; fi; } # shown by -v
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}
usage_error() {
  printf 'ERROR: %s (see --help)\n' "$*" >&2
  exit 2
}

# Print the help text: the comment block at the top of this file.
usage() {
  sed -n '2,/^$/s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
}

# One line of a table: row TITLE TEXT.
row() {
  printf '%-12s %s\n' "$1" "$2"
}

# A heading for a step of setup.
step() {
  printf '\n== %s\n' "$*"
}

# ---- Asking -----------------------------------------------------------------

interactive() { [[ -t 0 ]]; }

# ask QUESTION [DEFAULT]: read a line into $answer; empty means DEFAULT.
ask() {
  interactive || die "\"$1\" needs an answer, but there's no terminal to ask on."
  local prompt="$1 "
  if [[ -n ${2-} ]]; then prompt="$1 [$2] "; fi
  IFS= read -rep "$prompt" answer || die "No answer, so stopped."
  answer=${answer:-${2-}}
}

# ask_secret QUESTION: read a line without showing it, into $secret.
ask_secret() {
  interactive || die "\"$1\" has to be typed in, but there's no terminal."
  IFS= read -rsp "$1 " secret || die "No answer, so stopped."
  printf '\n' >&2
}

# confirm QUESTION: true if the answer is yes. --yes answers yes; without a
# terminal to ask on, it stops.
confirm() {
  if ((assume_yes)); then
    detail "$1 yes (--yes)"
    return 0
  fi
  interactive || die "$1 There's no terminal to ask on: give --yes to go ahead."
  local reply_
  IFS= read -rp "$1 [y/N] " reply_ || return 1
  [[ ${reply_,,} == y || ${reply_,,} == yes ]]
}

# confirm_typed WARNING WORD: true once WORD is typed back, for what can't be
# undone. --yes skips it.
confirm_typed() {
  if ((assume_yes)); then
    detail "$1 (--yes)"
    return 0
  fi
  interactive || die "$1 There's no terminal to ask on: give --yes to go ahead."
  local typed
  printf '%s\n' "$1" >&2
  IFS= read -rp "Type $2 to go ahead: " typed || return 1
  [[ $typed == "$2" ]]
}

# open_page URL: open it in the browser, if there is one to open it in.
open_page() {
  if [[ -n ${DISPLAY-}${WAYLAND_DISPLAY-} ]] && command -v xdg-open >/dev/null; then
    xdg-open "$1" >/dev/null 2>&1 &
  fi
}

# countdown SECONDS: wait, showing how long is left.
countdown() {
  local left
  for ((left = $1; left > 0; left--)); do
    printf '\rWaiting %3d s ' "$left" >&2
    sleep 1
  done
  printf '\r%20s\r' '' >&2
}

# get_captcha PAGE: have a captcha solved on Signal's PAGE, and the
# signalcaptcha://... link it gives put in $captcha.
get_captcha() {
  interactive || die "Signal wants a captcha first: solve it at $1, and run this again with the signalcaptcha:// link it gives (see --help)."
  info "Signal wants a captcha solved first:"
  info "  1. Open $1"
  info "  2. Solve it. When \"Open Signal\" shows, right-click it and copy the link."
  info "     It starts with signalcaptcha:// and only works for a minute or so."
  open_page "$1"
  while true; do
    ask "Paste the link:"
    captcha=${answer//[[:space:]]/}
    if [[ $captcha == signalcaptcha://?* ]]; then return 0; fi
    info "That isn't it: the link starts with signalcaptcha://"
  done
}

# ---- Talking to signal-cli-rest-api -----------------------------------------

# uri TEXT: TEXT encoded for a URL.
uri() {
  jq -rn --arg text "$1" '$text | @uri'
}

# json [--arg NAME TEXT | --argjson NAME JSON]...: the request body, an object
# of those names and values, for the next request --body.
json() {
  jq -n "$@" '$ARGS.named' >"$body"
}

# with_avatar FILE: add the avatar, base64 in FILE, to the request body. Apart
# from json, as before jq 1.7 $ARGS.named leaves out --rawfile.
with_avatar() {
  jq --rawfile avatar "$1" '. + {base64_avatar: $avatar}' "$body" >"$body.new"
  mv -- "$body.new" "$body"
}

# The request body as -v and --dry-run show it: secrets hidden, avatars summed
# up.
shown_body() {
  jq -c 'with_entries(
      if .key == "pin" or .key == "captcha" then .value = "(hidden)"
      elif .key == "base64_avatar" then .value = "(\(.value | length) characters)"
      else . end)' "$body"
}

# request [--body] [--slow] METHOD PATH: send one request; with --body, what
# json wrote, and with --slow, waiting longer. The answer goes in $reply and
# its HTTP status in $status. True for a 2xx answer.
request() {
  local with_body=0 max=$TIMEOUT why
  while [[ $1 == --* ]]; do
    case $1 in
      --body) with_body=1 ;;
      --slow) max=$SLOW_TIMEOUT ;;
    esac
    shift
  done
  local method=$1 path=$2
  local -a args=(--silent --show-error --connect-timeout 5 --max-time "$max"
    --request "$method" --output "$reply" --write-out '%{http_code}')
  if ((with_body)); then
    args+=(--header 'Content-Type: application/json' --data-binary "@$body")
    detail "> $method $path $(shown_body)"
  else
    detail "> $method $path"
  fi
  : >"$reply"
  if ! status=$(curl "${args[@]}" "$url$path" 2>"$work/curl-error"); then
    why=$(<"$work/curl-error")
    if [[ $why == *"(7)"* ]]; then
      why+=". Is it running, and there? --url says where"
    elif [[ $method != GET ]]; then
      why+=". It may have gone through all the same: see status"
    fi
    die "No answer from signal-cli-rest-api at $url: ${why#curl: }"
  fi
  detail "< HTTP $status"
  [[ $status == 2?? ]]
}

# change ARGS...: request ARGS, for a request that changes something. With
# --dry-run it only shows the request, and stops.
change() {
  if ((dry_run)); then
    local with_body=0
    while [[ $1 == --* ]]; do
      if [[ $1 == --body ]]; then with_body=1; fi
      shift
    done
    info "Would send: $1 $url$2"
    if ((with_body)); then info "With: $(shown_body)"; fi
    info "Dry run: nothing has been sent."
    exit 0
  fi
  request "$@"
}

# What the API said went wrong: its "error", or else the start of its answer.
api_error() {
  local error
  error=$(jq -r '.error // empty' "$reply" 2>/dev/null || true)
  if [[ -z $error ]]; then error=$(head -c 300 "$reply" | tr '\n' ' '); fi
  printf '%s' "${error:-no reason given}"
}

# fail WHAT: stop, saying WHAT went wrong and why.
fail() {
  die "$1: $(api_error) (HTTP $status)"
}

# print_json: the last answer as it is, for --json.
print_json() {
  if [[ -s $reply ]]; then jq . "$reply"; fi
}

# ---- The account ------------------------------------------------------------

# config_value KEY: the value of KEY = "..." in the bot's config, if any.
config_value() {
  if [[ -r $config_file ]]; then
    { grep -m 1 -E "^[[:space:]]*$1[[:space:]]*=" "$config_file" || true; } |
      sed -E "s/^[^=]*=[[:space:]]*[\"']([^\"']*)[\"'].*/\\1/;t;d"
  fi
}

# Where signal-cli-rest-api is: --url, the bot's NEJOMIBOT_SIGNAL_SERVICE or
# config, or the default.
settle_url() {
  if [[ -z $url ]]; then
    url=${NEJOMIBOT_SIGNAL_SERVICE:-$(config_value signal_service)}
    url=${url:-$DEFAULT_SERVICE}
  fi
  if [[ $url != http://* && $url != https://* ]]; then url=http://$url; fi
  url=${url%/}
}

read_about() {
  request GET /v1/about || fail "signal-cli-rest-api at $url didn't say what it is"
  cp "$reply" "$work/about.json"
  api_version=$(jq -r '.version // "?"' "$reply")
  api_mode=$(jq -r '.mode // "?"' "$reply")
}

# Each by its phone number, or its Signal ID if it has none. Since its
# numberless support (787d204e, 2026-10-22) signal-cli-rest-api lists them
# as {"number": ..., "aci": ...}; before, by number alone.
list_accounts() {
  request GET /v1/accounts || fail "Can't list the accounts"
  mapfile -t accounts < <(jq -r '.[] | if type == "string" then .
    elif (.number // "") != "" then .number else .aci // empty end' "$reply")
}

# is_registered NUMBER: true if signal-cli has the account.
is_registered() {
  local known
  list_accounts
  for known in "${accounts[@]}"; do
    if [[ $known == "$1" ]]; then return 0; fi
  done
  return 1
}

# The account from --account, NEJOMIBOT_ACCOUNT or the bot's config.
configured_account() {
  account=${account:-${NEJOMIBOT_ACCOUNT:-$(config_value account)}}
}

# use_account [any]: settle the account: --account, NEJOMIBOT_ACCOUNT,
# the bot's config, or else the only one signal-cli has. Unless "any", it
# must be registered in signal-cli, and may be a Signal ID, for an account
# without a number; "any" is for registering, which takes a number.
use_account() {
  configured_account
  if [[ -z $account ]]; then
    list_accounts
    case ${#accounts[@]} in
      0) die "signal-cli has no account yet: run setup, or register or link." ;;
      1)
        account=${accounts[0]}
        detail "Using the only account, $account"
        ;;
      *) die "signal-cli has ${#accounts[@]} accounts, so choose one with --account: ${accounts[*]}" ;;
    esac
  fi
  account=${account,,}
  if [[ $account =~ ^[0-9a-f]{32}$ ]]; then # a Signal ID without its dashes
    account=${account:0:8}-${account:8:4}-${account:12:4}-${account:16:4}-${account:20}
  fi
  if [[ ${1-} == any ]]; then
    [[ $account =~ $PHONE_NUMBER ]] ||
      die "Not a phone number in international format: $account (like +46701234567)"
  elif ! [[ $account =~ $PHONE_NUMBER || $account =~ $SIGNAL_ID ]]; then
    die "Neither a phone number in international format (like +46701234567) nor a Signal ID: $account"
  fi
  account_path=$(uri "$account")
  if [[ ${1-} != any ]] && ! is_registered "$account"; then
    die "$account isn't registered in signal-cli at $url${accounts[*]:+, which has ${accounts[*]}}: run setup, or register or link."
  fi
}

# The account's own entry, with its profile and username, into $work/me.json.
read_me() {
  request GET "/v1/contacts/$account_path/$account_path?all_recipients=true" ||
    fail "Can't read the profile"
  cp "$reply" "$work/me.json"
}

# me FILTER: something of the account's own entry, "" if unset.
me() {
  jq -r "$1 // \"\"" "$work/me.json"
}

show_profile() {
  local given family about username name
  given=$(me .profile.given_name)
  family=$(me .profile.lastname)
  about=$(me .profile.about)
  username=$(me .username)
  name="$given${family:+ $family}"
  row Name "${name:-none, so Signal shows the number}"
  if [[ -n $family ]]; then row "" "(given name $given, family name $family)"; fi
  row About "${about:-none}"
  if [[ $(me .profile.has_avatar) == true ]]; then row Avatar yes; else row Avatar none; fi
  if [[ -n $username ]]; then row Username "@$username"; else row Username none; fi
}

show_devices() {
  jq -r '
    def day: if . > 0 then . / 1000 | localtime | strftime("%Y-%m-%d") else "?" end;
    sort_by(.id)[]
    | [ "#\(.id)",
        (if .id == 1 then "primary" else "linked" end),
        (.name // "" | if . == "" then "(no name)" else . end),
        "added \(.creation_timestamp | day), seen \(.last_seen_timestamp | day)" ]
    | @tsv' "$1" |
    while IFS=$'\t' read -r id kind name dates; do
      printf '%-4s %-8s %-20s %s\n' "$id" "$kind" "$name" "$dates"
    done
}

# ---- Changing the profile ---------------------------------------------------

check_name() {
  local bytes
  bytes=$(jq -rn --arg text "$1" '$text | utf8bytelength')
  ((bytes <= NAME_MAX_BYTES)) ||
    die "A name holds at most $NAME_MAX_BYTES bytes in Signal, and that's $bytes (å, ä and ö take two each, emoji four)."
}

check_about() {
  local characters bytes
  characters=$(jq -rn --arg text "$1" '$text | length')
  bytes=$(jq -rn --arg text "$1" '$text | utf8bytelength')
  ((characters <= ABOUT_MAX_CHARACTERS)) ||
    die "About holds at most $ABOUT_MAX_CHARACTERS characters in Signal's apps, and that's $characters."
  ((bytes <= ABOUT_MAX_BYTES)) ||
    die "About holds at most $ABOUT_MAX_BYTES bytes in Signal, and that's $bytes."
}

# The bot's own avatar maker, as /avatar uses it, where its Python is, as in
# its container: FILE in, the avatar out, and its size and kind said.
BOT_AVATAR='
import sys
from pathlib import Path
from nejomibot.profile import make_avatar
avatar = make_avatar(Path(sys.argv[1]).read_bytes())
Path(sys.argv[2]).write_bytes(avatar.data)
print(f"{avatar.side}x{avatar.side} {avatar.format}")
'

# make_avatar FILE: the avatar to upload, from FILE, into $work/avatar. With
# ImageMagick, or else the bot's Python, made as the bot's /avatar makes one:
# upright, the middle square at most AVATAR_SIDE pixels wide, without
# metadata such as where it was taken, and a JPEG, or a PNG when it has
# see-through parts. Without either, FILE goes as it is, if Signal can show
# it.
make_avatar() {
  local file=$1 opaque kind size made
  if [[ $file == - ]]; then
    # From standard input, as from outside the bot's container:
    # podman exec -i nejomibot signal-account.sh profile --avatar - < logo.png
    [[ ! -t 0 ]] ||
      die "--avatar - takes the picture from standard input, as in: podman exec -i nejomibot signal-account.sh profile --avatar - < logo.png (-i, not -it)"
    file=$work/picture
    cat >"$file"
    [[ -s $file ]] || die "No picture came on standard input"
  fi
  [[ -f $file && -r $file ]] ||
    die "Can't read the picture $file. In the bot's container, which can't see your files, pipe it in with --avatar - (see --help)."
  if command -v magick >/dev/null; then
    opaque=$(magick identify -format '%[opaque]' "${file}[0]" 2>/dev/null) ||
      die "$file isn't a picture ImageMagick can read."
    local -a square=(-auto-orient -gravity center -crop 1:1 +repage
      -resize "${AVATAR_SIDE}x${AVATAR_SIDE}>" -strip)
    if [[ ${opaque,,} == true ]]; then
      magick "${file}[0]" "${square[@]}" -quality 90 "jpg:$work/avatar"
    else
      magick "${file}[0]" "${square[@]}" "png:$work/avatar"
    fi || die "ImageMagick couldn't make an avatar of $file"
    detail "Avatar: $(magick identify -format '%wx%h %m' "$work/avatar")"
  elif python3 -c 'import nejomibot.profile' 2>/dev/null; then
    made=$(python3 -c "$BOT_AVATAR" "$file" "$work/avatar") ||
      die "$file isn't a picture the bot can read."
    detail "Avatar: $made"
  else
    kind=$(file --brief --mime-type -- "$file" 2>/dev/null || true)
    case $kind in
      image/jpeg | image/png | image/gif | image/webp) ;;
      "") warn "Can't tell what kind of file $file is (no file command): sending it as it is." ;;
      *) die "$file is $kind, not a picture Signal shows as an avatar (JPEG, PNG, GIF or WebP)." ;;
    esac
    warn "Without ImageMagick the picture goes as it is, metadata and all: Signal shows its middle, in a circle."
    cp -- "$file" "$work/avatar"
  fi
  size=$(wc -c <"$work/avatar")
  ((size <= AVATAR_MAX_BYTES)) ||
    die "The avatar is $((size / 1024 / 1024)) MB, and Signal's Android app doesn't fetch one over 10 MB."
}

# set_profile NAME ABOUT_GIVEN ABOUT AVATAR AVATAR_FILE: change the profile.
# signal-cli-rest-api sets it as a whole: the given name always (the current
# one if NAME is empty), About only when given, and it removes the avatar
# unless one is sent. So the current avatar is fetched and sent back, unless
# AVATAR is new (from AVATAR_FILE) or remove. Needs read_me first.
set_profile() {
  local name=$1 about_given=$2 about=$3 avatar=$4 avatar_file=$5
  local given family
  given=$(me .profile.given_name)
  family=$(me .profile.lastname)
  if [[ -n $name ]]; then
    check_name "$name"
    if [[ -n $family ]]; then
      warn "The profile's family name is \"$family\", which signal-cli-rest-api can't change, so the name will show as \"$name $family\"."
      confirm "Go ahead?" || die "Nothing has been changed."
    fi
  else
    name=$given
    [[ -n $name ]] || die "The profile has no name, and signal-cli-rest-api needs one: give --name."
  fi
  if ((about_given)); then check_about "$about"; fi
  : >"$work/avatar.b64"
  case $avatar in
    new)
      make_avatar "$avatar_file"
      base64 -w 0 "$work/avatar" >"$work/avatar.b64"
      ;;
    keep)
      if [[ $(me .profile.has_avatar) == true ]]; then
        if request GET "/v1/contacts/$account_path/$account_path/avatar" && [[ -s $reply ]]; then
          detail "Sending the current avatar along, so it stays"
          base64 -w 0 "$reply" >"$work/avatar.b64"
        else
          warn "signal-cli can't give back the current avatar, and signal-cli-rest-api removes it unless it's sent along."
          confirm "Change the profile all the same, and lose the avatar?" || die "Nothing has been changed."
        fi
      fi
      ;;
  esac
  local -a fields=(--arg name "$name")
  if ((about_given)); then fields+=(--arg about "$about"); fi
  json "${fields[@]}"
  if [[ -s $work/avatar.b64 ]]; then with_avatar "$work/avatar.b64"; fi
  change --body --slow PUT "/v1/profiles/$account_path" || fail "Signal didn't take the profile"
  info "Profile changed."
}

# set_username NAME: as Signal takes it; it adds a number unless NAME has one.
set_username() {
  local wanted=${1#@} link
  [[ $wanted =~ $USERNAME ]] ||
    die "$wanted can't be a Signal username: 3 to 32 letters, digits or _, not starting with a digit, maybe with a dot and 2 to 9 digits after it (name.42)."
  json --arg username "$wanted"
  if ! change --body --slow POST "/v1/accounts/$account_path/username"; then
    # signal-cli-rest-api loses signal-cli's reason
    if [[ $(api_error) == *"invalid signal-cli response"* ]]; then
      die "Signal turned down $wanted, and signal-cli-rest-api doesn't say why: most likely it's taken, or not allowed. Try another, or another number after the dot."
    fi
    fail "Signal didn't take the username $wanted"
  fi
  if ((json)); then
    print_json
    return
  fi
  row Username "@$(jq -r '.username' "$reply")"
  link=$(jq -r '.username_link // ""' "$reply")
  if [[ -n $link ]]; then row Link "$link (it starts a chat)"; fi
}

set_pin() {
  local pin
  ask_secret "New PIN (at least 4 digits or letters):"
  pin=$secret
  ((${#pin} >= 4)) || die "A Signal PIN has at least 4 digits or letters."
  ask_secret "The same PIN again:"
  [[ $secret == "$pin" ]] || die "The two PINs differ, so nothing has been changed."
  json --arg pin "$pin"
  change --body --slow POST "/v1/accounts/$account_path/pin" || fail "Signal didn't take the PIN"
  info "PIN set. Signal asks for it when $account is registered anew: keep it safe."
}

# everyone_or_nobody WORD: true or false for the API, or a failure.
everyone_or_nobody() {
  case ${1,,} in
    everyone | yes | true | on) printf true ;;
    nobody | no | false | off) printf false ;;
    *) return 1 ;;
  esac
}

# set_privacy SEEN FINDABLE: each true, false, or "" to leave it.
set_privacy() {
  local seen=$1 findable=$2
  if [[ $seen == true && $findable == false ]]; then
    warn "Signal's apps don't allow that: whoever sees the number can find the account by it."
    confirm "Set it all the same?" || die "Nothing has been changed."
  fi
  local -a fields=()
  if [[ -n $seen ]]; then fields+=(--argjson share_number "$seen"); fi
  if [[ -n $findable ]]; then fields+=(--argjson discoverable_by_number "$findable"); fi
  json "${fields[@]}"
  change --body --slow PUT "/v1/accounts/$account_path/settings" ||
    fail "Signal didn't take the settings"
  if [[ -n $seen ]]; then
    row Number "seen by $([[ $seen == true ]] && echo everyone || echo nobody)"
  fi
  if [[ -n $findable ]]; then
    row Findable "by number: $([[ $findable == true ]] && echo everyone || echo nobody)"
  fi
}

# ---- Registering and linking ------------------------------------------------

# Settle the number to register: --account, the bot's config, or asked for.
number_to_register() {
  configured_account
  if [[ -z $account ]]; then
    ask "The phone number to register, like +46701234567:"
    account=${answer//[[:space:]]/}
  fi
  use_account any
  if is_registered "$account"; then
    warn "$account is registered in signal-cli already: registering it again starts afresh, with a new code."
    confirm "Register it again?" || die "Nothing has been changed."
  fi
}

# register VOICE CAPTCHA: have Signal send a verification code, by SMS or by a
# call (VOICE 1), going through what it may want first: a captcha, or a
# minute's wait before it calls.
register() {
  local voice=$1 error
  captcha=$2
  while true; do
    local -a fields=(--argjson use_voice false)
    if ((voice)); then fields=(--argjson use_voice true); fi
    if [[ -n $captcha ]]; then fields+=(--arg captcha "$captcha"); fi
    json "${fields[@]}"
    if change --body --slow POST "/v1/register/$account_path"; then break; fi
    error=$(api_error)
    case $error in
      *"Captcha required"* | *"Invalid captcha"*)
        if [[ $error == *"Invalid captcha"* ]]; then
          info "That captcha didn't work: they're only good for a minute or so."
        fi
        get_captcha "$REGISTRATION_CAPTCHA"
        ;;
      *"Couldn't use SMS verification"*)
        ((!voice)) || fail "Signal didn't send a code"
        info "Signal can't send $account an SMS, but it can call with the code."
        confirm "Wait the minute Signal wants, and have it call?" || die "No code has been sent."
        countdown 60
        voice=1
        ;;
      *) fail "Signal didn't send a code" ;;
    esac
  done
  if ((voice)); then
    info "Signal is calling $account with the code."
  else
    info "Signal is sending $account the code by SMS."
  fi
}

# verify CODE ASK_PIN: finish registering with the code Signal sent, and the
# registration lock PIN if the number has one: asked for first if ASK_PIN is
# 1, or once Signal wants it.
verify() {
  local code=${1//[^0-9]/} pin=""
  [[ $code =~ ^[0-9]{6}$ ]] || die "A Signal code has 6 digits, like 123-456."
  if (($2)); then
    ask_secret "The registration lock PIN:"
    pin=$secret
  fi
  while true; do
    if [[ -n $pin ]]; then json --arg pin "$pin"; else json; fi
    if change --body --slow POST "/v1/register/$account_path/verify/$code"; then break; fi
    case $(api_error) in
      *"locked with a pin"* | *"Invalid pin"*)
        info "$(api_error | head -n 1)"
        interactive || die "Signal wants the registration lock PIN: run verify again, with --pin."
        ask_secret "The registration lock PIN:"
        pin=$secret
        ;;
      *) fail "Signal didn't take the code" ;;
    esac
  done
  info "$account is registered."
}

# get_code: have the code Signal sent typed in, into $answer. Enter, when none
# came, has Signal send it again, or call with it, as its apps offer: its
# first SMS doesn't always come (on 2026-10-23 the one sent right after a
# captcha never did, twice, while the next one came at once).
get_code() {
  local voice
  while ask "The code Signal sent (Enter if none came):" && [[ -z $answer ]]; do
    ask "Have Signal send it again by SMS (s), or call with it (c)?" s
    voice=0
    if [[ ${answer,,} == c* ]]; then voice=1; fi
    (register "$voice" "") || true
  done
}

# link_device NAME: make signal-cli a linked device of a phone, called NAME
# there: show the QR code to scan, then wait for the new account to show up.
link_device() {
  local name=$1 link new="" waited=0 known
  local -a before
  warn "Linked to a phone, the bot takes what its owner types in a direct chat as sent by the other person, and runs it as theirs: an admin's commands too. The bot needs a number of its own, registered (see --help, LINKED)."
  confirm "Link to a phone all the same?" || die "Nothing has been changed."
  list_accounts
  before=("${accounts[@]}")
  if command -v qrencode >/dev/null; then
    change GET "/v1/qrcodelink/raw?device_name=$(uri "$name")" || fail "Can't start linking"
    link=$(jq -r '.device_link_uri' "$reply")
    qrencode -t ansiutf8 -m 2 "$link"
  else
    change GET "/v1/qrcodelink?device_name=$(uri "$name")" || fail "Can't start linking"
    cp "$reply" "$work/link.png"
    info "qrencode isn't installed, so the QR code is in $work/link.png (until this ends)."
    open_page "$work/link.png"
  fi
  info "On the phone: Signal > Settings > Linked devices > Link a new device,"
  info "and scan this code. Waiting for it, $((LINK_WAIT / 60)) minutes at most..."
  while ((waited < LINK_WAIT)) && [[ -z $new ]]; do
    sleep 3
    waited=$((waited + 3))
    list_accounts
    for known in "${accounts[@]}"; do
      if [[ " ${before[*]} " != *" $known "* ]]; then new=$known; fi
    done
  done
  [[ -n $new ]] || die "Not linked within $((LINK_WAIT / 60)) minutes: run link again, for a new code."
  account=$new
  account_path=$(uri "$account")
  info "Linked: signal-cli has $account now, as the device \"$name\"."
  local configured
  configured=$(config_value account)
  if [[ -n $configured && $configured != "$account" ]]; then
    warn "The bot's config has account = \"$configured\": make it \"$account\"."
  fi
}

# ---- Commands ---------------------------------------------------------------

cmd_status() {
  (($# == 0)) || usage_error "status takes no arguments"
  read_about
  use_account
  read_me
  request GET "/v1/devices/$account_path" || fail "Can't list the devices"
  cp "$reply" "$work/devices.json"
  request GET "/v1/identities/$account_path" || fail "Can't list the safety numbers"
  cp "$reply" "$work/identities.json"
  if ((json)); then
    jq -n --arg account "$account" --slurpfile about "$work/about.json" \
      --slurpfile me "$work/me.json" --slurpfile devices "$work/devices.json" \
      --slurpfile identities "$work/identities.json" --args \
      '{about: $about[0], account: $account, accounts: $ARGS.positional,
        me: $me[0], devices: $devices[0], identities: $identities[0]}' "${accounts[@]}"
    return
  fi
  info "signal-cli-rest-api $api_version, $api_mode mode, at $url"
  info ""
  row Account "$account (signal-cli has ${#accounts[@]})"
  show_profile
  info ""
  show_devices "$work/devices.json"
  info ""
  jq -r 'length as $all
    | (map(select(.status == "TRUSTED_VERIFIED")) | length) as $verified
    | (map(select(.status == "UNTRUSTED")) | length) as $untrusted
    | "Safety numbers: \($all), \($verified) verified, \($untrusted) untrusted"' \
    "$work/identities.json"
}

cmd_setup() {
  (($# == 0)) || usage_error "setup takes no arguments"
  ((!dry_run)) || die "setup asks as it goes, so it can't make a dry run: give --dry-run to the commands it uses."
  interactive || die "setup asks questions, so it needs a terminal."
  read_about
  info "signal-cli-rest-api $api_version, $api_mode mode, at $url"
  if [[ $api_mode != json-rpc* ]]; then
    warn "The bot needs json-rpc mode: MODE=json-rpc on the container."
  fi

  step "The account"
  configured_account
  if [[ $account =~ $PHONE_NUMBER ]] && is_registered "$account"; then
    info "$account is registered in signal-cli already."
  else
    info "The bot needs a number of its own, registered here; linked to a phone, it"
    info "would take commands typed on the phone as sent by the other person."
    ask "Register a number as a new Signal account (r), or link to a phone with Signal (l)?" r
    case ${answer,,} in
      r*)
        number_to_register
        register 0 ""
        get_code
        verify "$answer" 0
        ;;
      l*) link_device "$DEFAULT_DEVICE" ;;
      *) die "Neither r nor l: stopped." ;;
    esac
  fi
  use_account
  read_me

  step "The profile"
  show_profile
  local name about="" about_given=0 avatar=keep avatar_file=""
  ask "Name (Enter keeps it):"
  name=$answer
  ask "About (Enter keeps it, - removes it):"
  case $answer in
    "") ;;
    -) about_given=1 ;;
    *) about=$answer about_given=1 ;;
  esac
  ask "Avatar, a picture file (Enter keeps it, - removes it):"
  case $answer in
    "") ;;
    -) avatar=remove ;;
    *) avatar=new avatar_file=${answer/#\~/$HOME} ;;
  esac
  if [[ -n $name || $avatar != keep ]] || ((about_given)); then
    if (set_profile "$name" "$about_given" "$about" "$avatar" "$avatar_file"); then
      read_me
    else
      warn "The profile stays as it was; change it later with: profile"
    fi
  fi
  if [[ -z $(me .profile.given_name) ]]; then
    warn "The profile has no name, so Signal shows the number."
  fi

  step "The username"
  info "With a username, people can start a chat without the number."
  while ask "Username (Enter skips it):" && [[ -n $answer ]]; do
    if (set_username "$answer"); then break; fi
  done

  step "The PIN"
  info "A registration lock PIN stops anyone else registering the number, even"
  info "with its SMS code. Only for a number registered here, not linked."
  if confirm "Set a PIN?"; then
    (set_pin) || warn "No PIN set; set it later with: pin"
  fi

  step "Privacy"
  local seen findable
  ask "Who sees the phone number: everyone or nobody? (Enter leaves it)"
  seen=$(everyone_or_nobody "$answer") || seen=""
  if [[ -n $answer && -z $seen ]]; then info "Neither everyone nor nobody, so that stays."; fi
  ask "Who can find the account by its number: everyone or nobody? (Enter leaves it)"
  findable=$(everyone_or_nobody "$answer") || findable=""
  if [[ -n $answer && -z $findable ]]; then info "Neither everyone nor nobody, so that stays."; fi
  if [[ -n $seen || -n $findable ]]; then
    (set_privacy "$seen" "$findable") || warn "Privacy unchanged; set it later with: privacy"
  fi

  step "Done"
  cmd_status
  local configured
  configured=$(config_value account)
  if [[ $configured != "$account" ]]; then
    info ""
    info "The bot uses it with account = \"$account\" in its config."
  fi
}

cmd_register() {
  local voice=0 code_captcha=""
  while (($#)); do
    case $1 in
      --voice) voice=1 ;;
      --captcha)
        (($# > 1)) || usage_error "--captcha needs the signalcaptcha:// link"
        code_captcha=$2
        shift
        ;;
      *) usage_error "Unknown register option: $1" ;;
    esac
    shift
  done
  number_to_register
  register "$voice" "$code_captcha"
  if interactive; then
    get_code
    verify "$answer" 0
    info "Next, its name: ${0##*/} profile --name NAME"
  else
    info "Then: ${0##*/} verify CODE"
  fi
}

cmd_verify() {
  local code="" ask_pin=0
  while (($#)); do
    case $1 in
      --pin) ask_pin=1 ;;
      -*) usage_error "Unknown verify option: $1" ;;
      *)
        [[ -z $code ]] || usage_error "Give one code"
        code=$1
        ;;
    esac
    shift
  done
  [[ -n $code ]] || usage_error "verify needs the CODE Signal sent"
  configured_account
  [[ -n $account ]] || die "Which number? Give it with --account."
  use_account any
  verify "$code" "$ask_pin"
  info "Next, its name: ${0##*/} profile --name NAME"
}

cmd_link() {
  (($# <= 1)) || usage_error "link takes one device name"
  link_device "${1:-$DEFAULT_DEVICE}"
}

cmd_profile() {
  local name="" about="" about_given=0 avatar=keep avatar_file="" changes=0
  while (($#)); do
    case $1 in
      --name)
        (($# > 1)) || usage_error "--name needs the name"
        name=$2 changes=1
        [[ -n $name ]] || usage_error "--name needs the name"
        shift
        ;;
      --about)
        (($# > 1)) || usage_error "--about needs the text"
        about=$2 about_given=1 changes=1
        shift
        ;;
      --no-about) about="" about_given=1 changes=1 ;;
      --avatar)
        (($# > 1)) || usage_error "--avatar needs a picture file"
        avatar=new avatar_file=$2 changes=1
        shift
        ;;
      --no-avatar) avatar=remove changes=1 ;;
      *) usage_error "Unknown profile option: $1" ;;
    esac
    shift
  done
  use_account
  read_me
  if ((changes)); then
    set_profile "$name" "$about_given" "$about" "$avatar" "$avatar_file"
    read_me
  fi
  if ((json)); then
    jq . "$work/me.json"
    return
  fi
  show_profile
  if ((!changes)); then
    info "(signal-cli-rest-api doesn't show the emoji before About)"
  fi
}

cmd_username() {
  (($# <= 1)) || usage_error "Give one username"
  use_account
  case ${1-} in
    "")
      read_me
      if ((json)); then
        jq '{username}' "$work/me.json"
      elif [[ -n $(me .username) ]]; then
        row Username "@$(me .username)"
      else
        info "No username."
      fi
      ;;
    --remove)
      read_me
      [[ -n $(me .username) ]] || die "There's no username to remove."
      confirm "Remove the username @$(me .username)? Its link stops working, and anyone may take it." ||
        die "Nothing has been changed."
      change --slow DELETE "/v1/accounts/$account_path/username" ||
        fail "Signal didn't remove the username"
      info "Username removed."
      ;;
    -*) usage_error "Unknown username option: $1" ;;
    *) set_username "$1" ;;
  esac
}

cmd_pin() {
  case ${1-} in
    "")
      use_account
      set_pin
      ;;
    --remove)
      use_account
      confirm "Remove the registration lock PIN? Then anyone who gets an SMS code for $account can register it." ||
        die "Nothing has been changed."
      change --slow DELETE "/v1/accounts/$account_path/pin" || fail "Signal didn't remove the PIN"
      info "PIN removed."
      ;;
    *) usage_error "pin takes no PIN: it's asked for, to stay out of the shell history" ;;
  esac
}

cmd_privacy() {
  local seen="" findable=""
  while (($#)); do
    case $1 in
      --number-seen-by)
        (($# > 1)) || usage_error "--number-seen-by needs everyone or nobody"
        seen=$(everyone_or_nobody "$2") || usage_error "--number-seen-by is everyone or nobody"
        shift
        ;;
      --findable-by-number)
        (($# > 1)) || usage_error "--findable-by-number needs everyone or nobody"
        findable=$(everyone_or_nobody "$2") || usage_error "--findable-by-number is everyone or nobody"
        shift
        ;;
      *) usage_error "Unknown privacy option: $1" ;;
    esac
    shift
  done
  if [[ -z $seen && -z $findable ]]; then
    info "Who sees the phone number, and who can find the account by it:"
    info "  ${0##*/} privacy --number-seen-by everyone|nobody --findable-by-number everyone|nobody"
    info "signal-cli-rest-api can't show how they're set now."
    return
  fi
  use_account
  set_privacy "$seen" "$findable"
}

# challenge_from WHO: send WHO a short message, and put the challenge Signal
# gives with a rate limit in $token. Stops if Signal takes the message, as
# then the account isn't rate-limited.
challenge_from() {
  json --arg number "$account" --argjson recipients "$(jq -cn --arg who "$1" '[$who]')" \
    --arg message "A test from the bot's admin, to see whether Signal lets the bot send. It can be ignored."
  if change --body --slow POST /v2/send; then
    info "Signal took the message to $1, so the account isn't rate-limited."
    exit 0
  fi
  [[ $status == 429 ]] || fail "Couldn't send to $1"
  token=$(jq -r '.challenge_tokens[0] // empty' "$reply")
  [[ -n $token ]] ||
    die "Signal rate-limits the account, but offers no captcha for it: wait for the limit to lift."
  info "Signal rate-limits the account, and lifts it for a solved captcha."
}

cmd_rate_limit() {
  local token="" to=""
  captcha=""
  while (($#)); do
    case $1 in
      --to)
        (($# > 1)) || usage_error "--to needs who to send the test message to"
        to=$2
        shift
        ;;
      *)
        if [[ -z $token ]]; then
          token=$1
        elif [[ -z $captcha ]]; then
          captcha=$1
        else
          usage_error "rate-limit takes the challenge TOKEN and maybe the CAPTCHA link, or --to WHO"
        fi
        ;;
    esac
    shift
  done
  [[ -n $token || -n $to ]] || usage_error "rate-limit needs the challenge TOKEN, or --to WHO to get one"
  [[ -z $token || -z $to ]] || usage_error "rate-limit takes the challenge TOKEN or --to WHO, not both"
  use_account
  if [[ -n $to ]]; then challenge_from "$to"; fi
  if [[ -z $captcha ]]; then get_captcha "$CHALLENGE_CAPTCHA"; fi
  json --arg challenge_token "$token" --arg captcha "$captcha"
  change --body --slow POST "/v1/accounts/$account_path/rate-limit-challenge" ||
    fail "Signal didn't lift the rate limit"
  info "Rate limit lifted: the bot can send again."
}

cmd_unregister() {
  local delete_account=false delete_data=false
  while (($#)); do
    case $1 in
      --delete-account) delete_account=true ;;
      --delete-local-data) delete_data=true ;;
      *) usage_error "Unknown unregister option: $1" ;;
    esac
    shift
  done
  use_account
  info "Unregistering $account: Signal stops delivering its messages to signal-cli,"
  info "and the bot stops working until it's registered or linked again."
  if [[ $delete_account == true ]]; then
    warn "--delete-account deletes the Signal account itself, for good: its profile, username and groups go, and the number has to start afresh."
  fi
  if [[ $delete_data == true ]]; then
    info "--delete-local-data deletes what signal-cli keeps of it too: keys, contacts and groups."
  fi
  confirm_typed "This can't be undone." "$account" || die "Nothing has been changed."
  json --argjson delete_account "$delete_account" --argjson delete_local_data "$delete_data"
  change --body --slow POST "/v1/unregister/$account_path" || fail "Signal didn't unregister it"
  info "$account is unregistered."
}

cmd_delete_local_data() {
  local anyway=false
  case ${1-} in
    "") ;;
    --even-if-registered) anyway=true ;;
    *) usage_error "Unknown delete-local-data option: $1" ;;
  esac
  use_account any
  if [[ $anyway == true ]]; then
    warn "$account may still be registered: without its keys, signal-cli can't read what Signal still delivers to it."
  fi
  confirm_typed "This deletes all signal-cli keeps of $account: keys, contacts and groups. It can't be undone." "$account" ||
    die "Nothing has been changed."
  json --argjson ignore_registered "$anyway"
  change --body --slow DELETE "/v1/devices/$account_path/local-data" ||
    fail "signal-cli didn't delete it"
  info "What signal-cli kept of $account is deleted."
}

cmd_devices() {
  local what=${1-list} id name link
  if (($#)); then shift; fi
  use_account
  case $what in
    list)
      (($# == 0)) || usage_error "devices takes no more arguments"
      request GET "/v1/devices/$account_path" || fail "Can't list the devices"
      if ((json)); then print_json; else show_devices "$reply"; fi
      ;;
    add)
      (($# == 1)) || usage_error "devices add needs the device's link"
      link=$1
      [[ $link == sgnl://linkdevice\?* || $link == tsdevice:* ]] ||
        die "That isn't a device link: it starts with sgnl://linkdevice?"
      json --arg uri "$link"
      change --body --slow POST "/v1/devices/$account_path" || fail "Signal didn't link the device"
      info "Linked: it shows in devices once it has finished setting up."
      ;;
    remove)
      (($# == 1)) || usage_error "devices remove needs the device ID"
      id=$1
      [[ $id =~ ^[0-9]+$ ]] || usage_error "A device ID is a number, as devices shows"
      ((id != 1)) || die "Device 1 is the primary device, which can't be unlinked: unregister ends it."
      request GET "/v1/devices/$account_path" || fail "Can't list the devices"
      name=$(jq -r --argjson id "$id" '.[] | select(.id == $id) | .name // "(no name)"' "$reply")
      [[ -n $name ]] || die "There's no device $id: see devices."
      confirm "Unlink device $id, \"$name\"? It stops getting messages, and has to be linked anew." ||
        die "Nothing has been changed."
      change --slow DELETE "/v1/devices/$account_path/$id" || fail "Signal didn't unlink the device"
      info "Device $id unlinked."
      ;;
    sync)
      (($# == 0)) || usage_error "devices sync takes no more arguments"
      change --slow POST "/v1/contacts/$account_path/sync" || fail "Signal didn't take the contacts"
      info "Contact list sent to the linked devices."
      ;;
    *) usage_error "Unknown devices command: $what" ;;
  esac
}

cmd_identities() {
  (($# == 0)) || usage_error "identities takes no arguments"
  use_account
  request GET "/v1/identities/$account_path" || fail "Can't list the safety numbers"
  if ((json)); then
    print_json
    return
  fi
  cp "$reply" "$work/identities.json"
  request GET "/v1/contacts/$account_path?all_recipients=true" || fail "Can't list the contacts"
  jq -r --slurpfile identities "$work/identities.json" '
    def name: [.nickname.name, .name,
               ([.profile.given_name, .profile.lastname] | map(select(. != null and . != "")) | join(" ")),
               .username]
      | map(select(. != null and . != "")) | first;
    (map(select(.uuid != null and .uuid != "") | {key: .uuid, value: name}) | from_entries) as $names
    | $identities[0]
    | sort_by(($names[.uuid] // .number // .uuid) | ascii_downcase)[]
    | ($names[.uuid] // null) as $name
    | ( [$name, (if .number != "" then .number else null end), .uuid]
        | map(select(. != null)) | join(", ") ),
      "  " + ({TRUSTED_VERIFIED: "verified", TRUSTED_UNVERIFIED: "trusted, not verified",
               UNTRUSTED: "UNTRUSTED: changed, and not trusted yet"}[.status] // .status),
      ( .safety_number // "" | gsub("[^0-9]"; "") | [scan(".{1,5}")]
        | select(length > 0) | (.[0:4], .[4:8], .[8:12]) | "  " + join(" ") ),
      ""' "$reply"
}

# trust WHO SAFETY_NUMBER verifies, as the bot's /trust does; trust WHO
# --unverified only accepts the keys there are, as signal-cli does on first
# use anyway, which matters after a safety number has changed.
cmd_trust() {
  (($# >= 2)) || usage_error "trust needs WHO and their SAFETY_NUMBER, or --unverified"
  local who=$1 unverified=0 digits=""
  shift
  case $1 in
    --unverified)
      (($# == 1)) || usage_error "--unverified takes nothing more"
      unverified=1
      ;;
    -*) usage_error "Unknown trust option: $1 (to accept the keys unverified: --unverified)" ;;
    *)
      digits=$*
      digits=${digits//[^0-9]/}
      ((${#digits} == 60)) || die "A safety number has 60 digits, and that's ${#digits}."
      ;;
  esac
  use_account
  if ((unverified)); then
    confirm "Accept the keys of $who as they are, without verifying them?" ||
      die "Nothing has been changed."
    json --argjson trust_all_known_keys true
  else
    json --arg verified_safety_number "$digits"
  fi
  change --body PUT "/v1/identities/$account_path/trust/$(uri "$who")" ||
    fail "signal-cli didn't trust it"
  if ((unverified)); then
    info "$who is trusted, but not verified. To verify, compare their safety"
    info "number with the one on their phone, then: ${0##*/} trust $who SAFETY_NUMBER"
  else
    info "$who is verified."
  fi
}

cmd_search() {
  (($#)) || usage_error "search needs phone numbers"
  local query="" number
  for number; do
    [[ $number =~ $PHONE_NUMBER ]] ||
      die "Not a phone number in international format: $number (like +46701234567)"
    query+="${query:+&}numbers=$(uri "$number")"
  done
  use_account
  request --slow GET "/v1/search/$account_path?$query" || fail "Signal didn't say"
  if ((json)); then
    print_json
    return
  fi
  jq -r '.[] | "\(.number)  \(if .registered then "on Signal" else "not on Signal" end)"' "$reply"
}

cmd_accounts() {
  (($# == 0)) || usage_error "accounts takes no arguments"
  list_accounts
  if ((json)); then
    print_json
  elif ((${#accounts[@]})); then
    printf '%s\n' "${accounts[@]}"
  else
    info "No accounts yet: run setup."
  fi
}

cmd_about() {
  (($# == 0)) || usage_error "about takes no arguments"
  read_about
  if ((json)); then
    print_json
    return
  fi
  row Version "$api_version (build $(jq -r '.build // "?"' "$reply"))"
  row Mode "$api_mode"
  row "API versions" "$(jq -r '.versions // [] | join(", ")' "$reply")"
  row URL "$url"
}

cmd_log_level() {
  case ${1-} in
    "")
      request GET /v1/configuration || fail "Can't read the configuration"
      if ((json)); then print_json; else row "Log level" "$(jq -r '.logging.Level' "$reply")"; fi
      ;;
    debug | info | warn)
      json --argjson logging "{\"Level\": \"$1\"}"
      change --body POST /v1/configuration || fail "The log level stays as it was"
      row "Log level" "$1"
      ;;
    *) usage_error "The log level is debug, info or warn" ;;
  esac
}

cmd_trust_mode() {
  (($# <= 1)) || usage_error "trust-mode takes one mode"
  read_about
  use_account
  case ${1-} in
    "")
      request GET "/v1/configuration/$account_path/settings" || fail "Can't read the trust mode"
      if ((json)); then
        print_json
      elif [[ $api_mode == json-rpc* ]]; then
        info "In $api_mode mode, the container's JSON_RPC_TRUST_NEW_IDENTITIES sets it:"
        info "always, on-first-use or never (signal-cli's default: on-first-use)."
        info "signal-cli-rest-api's own setting is $(jq -r '.trust_mode' "$reply"), unused in this mode."
      else
        row "Trust mode" "$(jq -r '.trust_mode' "$reply")"
      fi
      ;;
    always | on-first-use | never)
      if [[ $api_mode == json-rpc* ]]; then
        die "In $api_mode mode it's set on the container: JSON_RPC_TRUST_NEW_IDENTITIES=$1, and a restart."
      fi
      json --arg trust_mode "$1"
      change --body POST "/v1/configuration/$account_path/settings" || fail "The trust mode stays as it was"
      row "Trust mode" "$1"
      ;;
    *) usage_error "The trust mode is always, on-first-use or never" ;;
  esac
}

# ---- Main -------------------------------------------------------------------

main() {
  local -a rest=()
  local tool command
  # Options go before or after the command. The values of the commands' own
  # options go through untouched, even when they start with a dash.
  while (($#)); do
    case $1 in
      -u | --url | -a | --account | -c | --config)
        (($# > 1)) || usage_error "$1 needs a value"
        case $1 in
          -u | --url) url=$2 ;;
          -a | --account) account=$2 ;;
          *) config_file=$2 ;;
        esac
        shift
        ;;
      -y | --yes) assume_yes=1 ;;
      -n | --dry-run) dry_run=1 ;;
      -j | --json) json=1 ;;
      -v | --verbose) verbose=1 ;;
      -h | --help)
        usage
        exit 0
        ;;
      --name | --about | --avatar | --captcha | --number-seen-by | --findable-by-number | --to)
        rest+=("$1")
        if (($# > 1)); then
          rest+=("$2")
          shift
        fi
        ;;
      *) rest+=("$1") ;;
    esac
    shift
  done
  set -- "${rest[@]}"
  command=${1:-status}
  if (($#)); then shift; fi

  for tool in curl jq; do
    command -v "$tool" >/dev/null || die "$tool is needed, but isn't installed."
  done
  config_file=${config_file:-${NEJOMIBOT_CONFIG:-$(dirname -- "${BASH_SOURCE[0]}")/../config.toml}}
  settle_url

  case $command in
    status) cmd_status "$@" ;;
    setup) cmd_setup "$@" ;;
    register) cmd_register "$@" ;;
    verify) cmd_verify "$@" ;;
    link) cmd_link "$@" ;;
    profile) cmd_profile "$@" ;;
    username) cmd_username "$@" ;;
    pin) cmd_pin "$@" ;;
    privacy) cmd_privacy "$@" ;;
    rate-limit) cmd_rate_limit "$@" ;;
    unregister) cmd_unregister "$@" ;;
    delete-local-data) cmd_delete_local_data "$@" ;;
    devices) cmd_devices "$@" ;;
    identities) cmd_identities "$@" ;;
    trust) cmd_trust "$@" ;;
    search) cmd_search "$@" ;;
    accounts) cmd_accounts "$@" ;;
    about) cmd_about "$@" ;;
    log-level) cmd_log_level "$@" ;;
    trust-mode) cmd_trust_mode "$@" ;;
    help) usage ;;
    *) usage_error "Unknown command: $command" ;;
  esac
}

main "$@"
