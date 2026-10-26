![Project banner](https://raw.githubusercontent.com/jodab/nejomibot/main/nejomibot/social-preview.png)

# nejomibot

[![CI](https://github.com/jodab/nejomibot/actions/workflows/ci.yml/badge.svg)](https://github.com/jodab/nejomibot/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jodab/nejomibot)](https://github.com/jodab/nejomibot/releases)

> **Disclaimer:** This project began as a playground for teaching myself to
> make better use of Claude Code. Everything here was written by AI, under my
> guidance.

A self-hosted Signal bot for a family or a group of friends: a daily post
with the day's holidays, birthdays and name days, the weather and a photo
from your library; commands for photos, the weather, reminders and shared
lists; and timers that run any command on a schedule. The admins manage it
from Signal.

- **Photos** at random, by album, date or moment, or from this day in an
  earlier year, with when and where they were taken, and optionally an age.
- **The day:** holidays in 35 countries, each group's birthdays and name
  days, and the weather and forecast for any place.
- **Your own commands:** timers, and specials that combine texts and
  commands.
- **Nine languages**, chosen per chat.
- **Private:** it answers only those you allow, takes admin commands only
  in a direct chat, and by default logs no phone numbers or message text.
- **Reliable and light:** health checks with external pings, an outbox that
  retries and outlasts restarts, and about 80 MB of memory.

It talks to Signal through [signalbot](https://pypi.org/project/signalbot/)
and [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
in json-rpc mode. **Image:** `docker.io/jodab/nejomibot` or
`ghcr.io/jodab/nejomibot`, tagged `latest` and with each version.
**Source:** [github.com/jodab/nejomibot](https://github.com/jodab/nejomibot).

## Getting started

You need a Linux host with Docker Compose or Podman (both containers take
about 450 MB of memory), an
[OpenWeatherMap API key](https://home.openweathermap.org/api_keys) (a new key
works within two hours), your photos (JPEG, PNG, GIF, WebP, AVIF or HEIC),
and a number for the bot that can receive a text message or a call and
isn't in use with Signal, as registering it signs it out everywhere else.
The bot can instead be
[linked to a phone](https://github.com/jodab/nejomibot#linking-to-a-phone).

```sh
mkdir -p ~/nejomibot/{data,photos,signal} && cd ~/nejomibot
curl -fsSLO https://raw.githubusercontent.com/jodab/nejomibot/main/deploy/compose.yaml
docker run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > data/config.toml
```

In `data/config.toml`, set `account` (the bot's number, as `+46700000000`),
`admins` (yours), `openweather_api_key`, `weather_city`, `timezone` and
`language` (`en`, `da`, `de`, `el`, `es`, `fi`, `fr`, `nb` or `sv`); in
`compose.yaml`, the photos volume and `TZ`. Then:

```sh
sudo chown -R 1000:1000 data signal && sudo chmod 700 data
docker compose up -d
docker compose exec nejomibot nejomibot-account setup
```

Both containers run as UID 1000 (rootless Podman: `podman unshare chown`;
another user: `user:`, owning `data`), and the photos must be readable by
everyone. With SELinux, add `:Z` to the `data` and `signal` volumes and
`,z` to the photos volume.

The bot waits for its account. `nejomibot-account setup` registers the
number, with a code by text message or call, or links the bot to a phone. If
Signal asks for a captcha, solve one at
[signalcaptchas.org](https://signalcaptchas.org/registration/generate.html)
and paste the `signalcaptcha://` link behind **Open Signal** within a
minute. Give the bot a name, and a PIN, which keeps others from registering
its number. Then, from an admin's phone:

1. Send the bot `/help`. Commands may start with `.`, `!` or `/`.
2. Once the bot has replied, add it to a group (before that, Signal may only
   invite it, which it doesn't accept), and allow the group from your direct
   chat: `/allow Family`. People: `/allow +46700000002`.
3. `/chats` numbers the chats; `/timer add 08:00 1 /today; /weather;
   /uniquephoto` posts to chat 1 daily, and `/timer run 1` tries it.

With Podman and systemd, use the
[Quadlets](https://github.com/jodab/nejomibot#podman-quadlets): they also
restart a container whose health check fails.

**No reply?** `admins` must hold your number, or if your Signal hides it
from everyone, your Signal ID, which `nejomibot-account identities` lists.
**A group is missing from `/chats`?** Signal only invited the bot: revoke
the invitation, and add it again.

## Commands

This page writes commands with `/`; the bot shows them with
`command_prefix`, `.` by default. `/help <command>` explains one, with
examples. Every language's names work in every chat (`/väder` is
`/weather`), and so do `/test` (`/status`), `/time` (`/info`), `/safety`
(`/contacts`) and `/day` (`/today`).

For everyone allowed:

| Command | Does |
|---|---|
| `/photo [<album>] [<date>]` | A random photo, taken in a period (`2017-05`, `2017-05-14 15`) or the nearest, or nearest a moment (`2024-06-01 15:00`) |
| `/sphoto [<album>] [<date>]` | The same, without a caption |
| `/uniquephoto [<album>]` | A photo not yet sent in the current round |
| `/onthisday [<album>]` | A photo from this day, or within three days of it, in an earlier year |
| `/albums` | The albums, with their photos, years, birth dates and shortcuts |
| `/cache [<album>]` | The number and size of the photos, by type |
| `/today` | The date and time, the holidays, and in a group, its birthdays and name days |
| `/weather [<city>]` | The weather in `weather_city`, or a place such as `Springfield,MO,US` |
| `/forecast [<city>]` | Today's and tomorrow's weather, temperatures and chance of rain or snow |
| `/info` | The time in the `clocks`, and the `exchange_rate` |
| `/ping` | `pong!`, and how long the message took |
| `/fortune [<library>]` | A fortune; `all`, or `list` for the libraries |
| `/remind <when> <text>` | A reminder in the chat (`18:00`, `30m`, `fri 17:00`, `2026-12-24 15:00`); alone, the list; `remove <n>` |
| `/list [add <items>]` | The chat's list: `add milk, eggs`, `remove 2,5`, `clear` |
| `/birthdays` | The coming birthdays: the group's, or all, for an admin in a direct chat |
| `/namedays` | The coming name days, likewise |
| `/language [<language>]` | The chat's language, set by an admin in a group; `default` resets it |
| `/help [<command>]` | The commands you may use, or one command's page |

For admins, in a direct chat:

| Command | Does |
|---|---|
| `/status` | The health checks, and the bot, account, network, container and host |
| `/album <album> [<birth date>]` | An album; sets its birth date (`-` removes it), or `shortcuts <names>` |
| `/today preview [<date>]` | What `/today` will say, in each group and a direct chat |
| `/contacts [<who>]` | Everyone the account knows, numbered; one person, with their safety number |
| `/contacts add <who> <name>` | Saves or renames a contact, also by number or `u:username` |
| `/trust [<who>] [<safety number>]` | The safety numbers; given one, marks it verified |
| `/allowed` | The allowed list |
| `/allow <who>` | Allows a person, or a group by name or ID |
| `/disallow <n>` | Takes someone off the allowed list |
| `/admins` | The admins |
| `/admin add <who> [<language>]` | Makes someone an admin; `/admin remove <n>` |
| `/profile` | The bot's name, About text, username and avatar |
| `/name <name>` | Sets the bot's name |
| `/about <text>` | Sets the About text, or `remove` |
| `/avatar` | Makes the picture sent with it the avatar, or `remove` |
| `/username <name>` | Sets the username, with a link to a chat with the bot, or `remove` |
| `/chats` | The chats that timers, `/msg` and `/run` post to, numbered |
| `/timers` | The timers |
| `/timer add <when> [<chats>] <commands>` | Adds a timer; `remove <n>`, `run <n>` |
| `/specials` | The specials |
| `/special add <name> <parts>` | Adds or changes a special; `shortcuts`, `everyone`, `admins`, `remove` |
| `/language <chats> <language>` | Sets the chats' language |
| `/msg <chats> <text>` | Posts a text to chats |
| `/run <chats> <commands>` | Posts commands' answers to chats |
| `/incoming [<n>,<n>]` | The latest direct messages from non-admins; forwards those given |
| `/birthday add <date> [<chats>] <who>` | Adds a birthday; `remove <n>` |
| `/nameday add <date> [<chats>] <who>` | Adds a name day; `remove <n>` |
| `/delete list` | The bot's latest messages, anywhere; `/delete <n>,<n>` deletes those |
| `/delivery` | How many received and read each of the bot's latest messages |
| `/selfpromote` | The bot's name and links, under its picture, to forward |

For admins, in any chat:

| Command | Does |
|---|---|
| `/delete` | Deletes the bot's latest message in the chat, then the one before |
| `/mention all [<text>]` | Mentions everyone in the group |

`/avatar` needs attachments, which the examples turn off
(`JSON_RPC_IGNORE_ATTACHMENTS=true`); `podman exec -i nejomibot
nejomibot-chat -a - /avatar < picture.png` sets one from the host. The
`bot_*` settings fill in what `data/bot.txt`, the profile the bot keeps,
lacks.

## Who may use what

- **Admins:** those in `admins`, and those they add with `/admin add` (in
  `data/admins.txt`). Admin commands work only in a direct chat, except
  `/delete` and `/mention all`. Only the configuration's admins add and
  remove admins and get the notices, and timers run as the first of them.
- **Everyone else** gets answers only if allowed: a person in a direct chat,
  or everyone in an allowed group, in that group. Allowed people who send
  something other than a command in a direct chat get a greeting, at most
  once a day.
- **A limit:** the bot answers each person at most `command_limit` commands
  (20) in `command_limit_minutes` (10); the admins, timers, `/run` and
  specials aren't limited.
- **Edits:** an edited command runs in place of the original, within a day,
  undoing what the original added or removed; posts and deletions aren't
  repeated.

## Timers

```
/timer add 08:00 1,2 /today; /weather; /uniquephoto   daily, to chats 1 and 2 of /chats
/timer add mon-fri 07:30 1 /weather
/timer add tomorrow 18:00 1 /photo                     once
/timer add every 2h /status                            without chats: to you
```

`<when>` is times (`08:00,18:30`), days and a time (`mon-fri`, `sat,sun`,
`weekdays`, `weekends`), a date and a time (`2026-12-24 15:00`, `tomorrow
08:00`), or an interval of 10 minutes or more (`every 2h`), in `timezone`.
The commands, separated by `;`, run as the first admin's in a direct chat,
and every chat gets the same photo. Timers can't run what changes timers,
specials, birthdays, albums or access, `/msg`, `/run`, a chat's own commands
(`/remind`, `/list`, `/birthdays`, `/namedays`), `/delete` or `/contacts
add`. A run missed while the bot was down is made at its start, up to an
hour late. `nejomibot-timers` edits `data/timers.txt` from a shell.

## Specials

```
/special add /morning Good morning! /today + /weather; /uniquephoto
/special shortcuts /morning /gm
/special everyone /morning
```

`;` or a line break starts a new message, a `+` on its own joins the parts
around it into one, and text before a command heads its answer, formatted as
given in Signal. A special has up to five parts and five shortcuts, can hold
any command a timer can run, but no special, and runs as whoever sends it.
`/special everyone` lets everyone allowed use it; the bot names any admin
commands in it, whose answers they would see.

## Photos

- Each folder directly in `photos_dir` is an album. `/album Alice shortcuts
  /alice` makes `/alice` mean `/photo Alice`.
- `/uniquephoto` sends every photo once before it starts a new round, and
  each album has its own round. The rounds are in `data/sent-photos.txt` and
  `data/album-rounds.txt`: delete the file, or the album's lines, to start
  over.
- When each photo was taken is read in the background at start, from new
  and changed files, into `data/photo-index.txt` and memory (about 400 bytes
  a photo; 47 s for 7,671 photos on a Raspberry Pi 4).
- Captions show the time in `timezone`. DateTimeOriginal counts as UTC when
  DateTimeDigitized is a whole time zone away from it; otherwise its offset
  tag applies, or else `photos_timezone`.
- With a birth date (`/album Alice 2019-06-15`, or `photos_birth_date` for
  the photos in no album), captions show the age.
- HEIC/HEIF is sent as JPEG, unless `photos_heif = false` leaves it out;
  [tools/tidy-photos.sh](https://github.com/jodab/nejomibot/blob/main/tools/tidy-photos.sh)
  converts, renames and deduplicates a library.
- A GPS position adds a map link (`photos_map`).

## Birthdays, name days and holidays

`holidays = ["SE", "GR"]` adds those countries' public holidays and common
observances to `/today`, from AT, AU, BE, BG, CA, CH, CY, CZ, DE, DK, EE, ES,
FI, FR, GB, GR, HR, HU, IE, IS, IT, LT, LU, LV, MT, NL, NO, NZ, PL, PT, RO,
SE, SI, SK and US; only Sweden's and Greece's, and the days others share
with them, are translated. Birthdays and name days show in groups only: a
contact's (`/birthday add 1990-03-14 Alice`) in the groups they're in, and
others' (`/birthday add 1940-05-01 1 Grandma`) in the chats given, or in
every group.

## Languages

`language` sets the bot's language, and `/language sv` a chat's own. Each is
two files in
[nejomibot/locale](https://github.com/jodab/nejomibot/tree/main/nejomibot/locale):
`<code>.po`, the messages, and `<code>.toml`, its words for commands, times
and subcommands. `tools/translations.sh <code>` starts one, and after the
messages change, updates every `.po` (it needs GNU gettext).

## The bot from a terminal

The image's tools run with `podman exec` or `docker compose exec`; each has
`--help`, and a shell in the container starts with a guide to them (`help`):

```sh
podman exec -it nejomibot nejomibot-chat                  # as the first admin's direct chat
podman exec nejomibot nejomibot-chat /weather Helsinki    # one message and its answers
podman exec -it nejomibot nejomibot-chat --to 1           # chat 1 of /chats, as the bot
podman exec -i nejomibot nejomibot-chat -a - "/msg 1 Look!" < photo.jpg
podman exec nejomibot nejomibot-chat --recent 20 --follow # messages received, in every chat
podman exec nejomibot nejomibot-timers                    # the timers
```

`--json` prints a JSON object a line, for scripts. `nejomibot-chat` reaches
the bot over an abstract Unix socket, which only its user and root may use.

## The Signal account

`nejomibot-account` registers or links the account, and manages its
profile, username, PIN, privacy, linked devices, safety numbers and rate
limits; `--dry-run` sends nothing.

```sh
podman exec -it nejomibot nejomibot-account                # the status
podman exec -i nejomibot nejomibot-account profile --avatar - < logo.png
podman run --rm -it --no-healthcheck --network container:signal \
  docker.io/jodab/nejomibot nejomibot-account setup        # without the bot
```

When Signal rate-limits the bot, `nejomibot-account rate-limit --to <your
number>` leads you through the captcha that lifts the limit.

### Linking to a phone

`nejomibot-account link` shows a QR code to scan in Signal on the phone
(**Settings > Linked devices**). The bot then needs no number, but what is
typed on the phone in a direct chat reaches it as if the other person had
sent it, as signalbot can't tell them apart, so it runs their commands, with
an admin's rights in a chat with an admin. The phone must come online every
30 days, or Signal unlinks the bot, and only the phone can set the PIN.

### An account without a phone number

Signal Android's beta registers accounts without a number, with a Signal
Login: an Account ID, which the bot calls the Signal ID, and a Recovery key.
Set `account` to the Signal ID, and give the bot a username, by which alone
people can find it. signal-cli-rest-api can link to such an account but not
restore it; signal-cli's `register --recovery-key` can, on
signal-cli-rest-api's data while it's stopped. People without a number go
by their Signal ID in `admins`, `/allow` and `/admin add`.

## Health checks

Every `healthcheck_minutes` (5), the bot checks signal-cli-rest-api (it
answers, in json-rpc mode, newer than 0.101), itself (no message has waited
15 minutes, and since the last round none was given up or failed with an
unknown outcome), Signal's servers (they list the linked devices), and
delivery (it hears receipts, and no three messages in a row have gone
unconfirmed for `unconfirmed_hours`, 12, with none confirmed since).
Failures are logged and lead `/status`; each round pings `healthcheck_url`,
such as a [healthchecks.io](https://healthchecks.io) URL, or its `/fail`,
with the results. The configuration's admins hear from the bot at each start
(`startup_notice`), at a rate limit, and when a safety number changes.

The image's health check is for liveness only: it never fails for Signal
or signal-cli-rest-api, which a restart wouldn't mend, nor while the bot
waits for its account. The Quadlets restart a container that fails it three
times running; Docker doesn't.

## Sending and Signal's rate limits

Each chat gets its messages in order. A send that surely failed is tried
again for `send_retry_hours` (3), marked late; a timeout isn't, as the
message may have arrived. Messages that have waited 30 seconds, and all
waiting at shutdown, are kept in `data/outbox` until sent. When Signal
rate-limits the bot (429), solving a captcha lifts the limit; meanwhile the
bot sends no receipts or typing, and tries only the oldest message, after 2
minutes, then twice as long each time, up to `rate_limit_retry_minutes`
(30), or soon after an admin's command.

## Which signal-cli-rest-api

The bot needs one newer than 0.101, the latest release, which crashes on
overlapping requests
([#885](https://github.com/bbernhard/signal-cli-rest-api/issues/885)) and
logs every message it receives
([#892](https://github.com/bbernhard/signal-cli-rest-api/issues/892)). Until
the next release, the examples in
[deploy/](https://github.com/jodab/nejomibot/tree/main/deploy) pin the CI
build `1792710189-ci` by digest; it reports its version as `unset`. Run it
in `json-rpc` mode: `json-rpc-native` has had bugs `json-rpc` hasn't, and
has no 32-bit ARM build. It has no authentication, so whoever reaches it
controls the account: the examples publish no port.

## Configuration

[config.example.toml](https://github.com/jodab/nejomibot/blob/main/config.example.toml)
(`/app/config.example.toml` in the image) describes every setting, aliases
included. The bot reads `NEJOMIBOT_CONFIG` (`/data/config.toml` in the
image), and `NEJOMIBOT_<SETTING>` variables override it (lists and tables as JSON).
An unknown or invalid setting stops the bot with its name.

`data_dir` (`/data`) must exist and belong to the bot's user. The bot
writes its files there atomically, readable by that user alone:

| File | Holds |
|---|---|
| `allowed.txt`, `admins.txt` | The allowed list, and the admins added |
| `timers.txt`, `specials.txt` | The timers and specials |
| `reminders.txt`, `lists.txt`, `languages.txt` | Each chat's reminders, list and language |
| `birthdays.txt`, `albums.txt` | Birthdays and name days; albums' birth dates and shortcuts |
| `sent-photos.txt`, `album-rounds.txt` | `/uniquephoto`'s rounds |
| `photo-index.txt` | When each photo was taken |
| `bot.txt` | The profile, with the avatar beside it |
| `outbox/`, `run.json` | Messages waiting; the last run's version and stop |

You may edit the allowed list, admins, timers, specials, reminders, lists,
birthdays, albums and languages by hand while the bot runs: the bot reads
them again when they change, and leaves comments and lines it can't read as
they are. `bot.txt` takes effect at the next start.

## Running it

The image runs as UID and GID 1000, or the user it's given, needs no
capabilities, and writes only to `/data`, which must belong to its user
(Podman's `:U`), and `/tmp`: the examples run it read-only, without new
privileges, with an init process. The photos go in `/photos`, read-only.

### Podman Quadlets

Copy [signal.container](https://github.com/jodab/nejomibot/blob/main/deploy/signal.container)
and [nejomibot.container](https://github.com/jodab/nejomibot/blob/main/deploy/nejomibot.container)
to `/etc/containers/systemd/` (rootless: `~/.config/containers/systemd/`,
`UserNS=keep-id:uid=1000,gid=1000` in place of `:U`, and `loginctl
enable-linger`), adjust the paths, and run `systemctl daemon-reload &&
systemctl start signal`, which starts the bot too. The bot shares
signal-cli-rest-api's network namespace, reaching it at `127.0.0.1:8080`
where nothing else can, and stops and starts with it. `signal.container`
checks signal-cli itself, where the image's own check only reaches the REST
layer.

### Updating

`docker compose pull && docker compose up -d`, or `podman pull
docker.io/jodab/nejomibot && systemctl restart nejomibot`. The
[changelog](https://github.com/jodab/nejomibot/blob/main/CHANGELOG.md) says
what to do, if anything, and a setting that must change stops the bot with
its name. A version tag in place of `latest` lets you choose when.

### Logs and verification

At `INFO`, the bot logs commands by name and the kind of chat, never phone
numbers, IDs or message text, which `log_level = "DEBUG"` adds; libraries
log at `WARNING`, where signalbot names whom a group message didn't reach.
Each release's images have signed build provenance;
[SECURITY.md](https://github.com/jodab/nejomibot/blob/main/SECURITY.md) has
more, and how to report a vulnerability:

```sh
gh attestation verify oci://docker.io/jodab/nejomibot:latest --repo jodab/nejomibot
```

## Development

```sh
uv sync                    # .venv: Python 3.15 and the locked dependencies
uv run pytest              # the tests, against a stand-in signal-cli-rest-api
uv run ruff check && uv run ruff format --check && uv run pyright
tools/build-image.sh       # the checks, then the amd64, arm64 and arm/v7 images
```

CI runs these, ShellCheck and an amd64 build on pushes to main and pull
requests; `tools/release.sh` releases what it passed.
[AGENTS.md](https://github.com/jodab/nejomibot/blob/main/AGENTS.md)
describes the design and the project's rules.

### Running from a checkout

The bot and its tools run on Python alone, without a container, and the
tests need nothing more. The bot needs a signal-cli-rest-api at
`signal_service`, such as the server's, published on its loopback
(`PublishPort=127.0.0.1:8080:8080` in `signal.container`) and reached with
`ssh -L 8080:127.0.0.1:8080 server`. Stop the server's bot first: two bots
on one account compete for its messages.

```sh
cp config.example.toml config.toml   # account, admins, debug_group, ...
NEJOMIBOT_DEBUG=1 NEJOMIBOT_PHOTOS_DIR=~/Pictures uv run nejomibot
uv run nejomibot-chat /help          # in another terminal, as the first admin
```

Debug mode talks only to `debug_group` and the admins, and keeps its files
in a new temporary folder; for lasting ones, `mkdir -m 700 data` and set
`NEJOMIBOT_DATA_DIR=data`. Without uv, a Python 3.15 virtual environment
with `pip install -e . --group dev` (pip 25.1 or later) works too.

## License

MIT ([LICENSE](https://github.com/jodab/nejomibot/blob/main/LICENSE));
releases up to 0.99.14 were GPL-3.0-or-later, and remain so. The fortune
libraries but `fortunes_svenska`, the bot's own, come from
[fortune-mod](https://github.com/shlomif/fortune-mod), as Debian ships them,
under its BSD license
([LICENSES/fortune-mod.txt](https://github.com/jodab/nejomibot/blob/main/LICENSES/fortune-mod.txt)).
