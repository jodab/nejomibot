# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

nejomibot is a self-hosted Signal bot for a family or a group of friends: a
daily post (the day's holidays, birthdays and name days, the weather, and a
photo of the day), everyday commands for photos, the weather, reminders and
shared lists, timers and the admins' own commands, and admin commands in
direct chats. It talks to Signal through signalbot, which talks to
signal-cli-rest-api in json-rpc mode, and it ships as a container image.

## The owner's instructions

From the owner of the project, in no particular order of priority:

1. Never change any of the bot's user-facing functionality unless
   specifically asked to. If a change becomes necessary, ask what to do.
2. Keep the code easy to understand and maintain, and reliable, stable,
   secure and privacy-respecting. Keep this in mind for any code or function
   written or considered. Bonus points for less and smaller code, and for
   reusing code and functions as much as possible, as long as that doesn't
   come at the cost of the other instructions.
3. Always follow the best known practices and standards in every decision
   for this project. That includes bot behavior, container maintenance,
   startup, restarts and shutdown, error reports, health checks, logging,
   Python, linting, unit tests, Podman and systemd interactions: essentially
   everything this project does.
4. Keep memory and resource use low: light enough that the project can be
   hosted on free or essentially free services online.
5. Do our very best not to hit rate limits on Signal's servers.
6. Make the bot as performant as possible, reducing latency wherever we can.
   Performance and low resource use (4, 7) are both highly important; when
   they pull against each other, performance is slightly favored.
7. Keep the final image as small and light (RAM, CPU, disk) as possible:
   only what is strictly necessary goes into it.
8. Use minimal resources to build the images as well.
9. Measure, test and verify every change, for accuracy and for future
   improvements.
10. Uptime and availability are everything. Whenever something is modified,
    changed or pushed, or an image is built, it must always work and be 100%
    stable and reliable. This rule trumps all others.
11. Any workaround added to our code to get around bugs or issues in
    signal-cli-rest-api should be documented as such, and checked again in
    the future in case the bug or problem no longer exists, so that we can
    remove the workaround.
12. Always reuse code whenever possible, and refactor whenever it will
    benefit us.

User-facing means anything people see or can do in Signal: the commands and
their names, the replies and their wording, who may use what, and what is
posted where and when. When unsure whether a change is user-facing, ask.

## Working agreements

- **Standards first.** Prefer the established convention (OCI/Docker, Python
  packaging, systemd/Quadlet, shell). When something is only a local
  convenience or deviates from the norm, say so and name the standard
  alternative.
- **signalbot first.** Talk to Signal through signalbot's public API for
  everything it can do, and check newer signalbot releases before going
  around it. Direct signal-cli-rest-api requests live only in
  `nejomibot/rest.py`, each function saying in a comment what signalbot
  lacks.
- **The repository is public.** No real names, phone numbers, group IDs,
  dates, places or hostnames in tracked files, tests and documentation
  included. Use made-up values (`+4670000000x`, `group.ZmFtaWx5`, Alice and
  Bob, Stockholm and Helsinki); personal values belong in the untracked
  `config.toml`. Don't rewrite git history unless asked.
- **0.99.x until 1.0** (the owner's decision, 2026-10-19): every release is a
  patch release until the owner says it is time for 1.0; a minor release
  would be 0.100.0. `tools/release.sh` stops on minor and major releases, and
  its guard comes out only when the owner says so.
- **Commits.** Commit or push only when asked. Commits are signed; if signing
  doesn't work from the session, leave the commit to the owner.
- **The live Signal account.** When testing against it, send only to the
  group set aside for testing, prefer read-only requests and
  `signal-account.sh --dry-run`, and ask before changing the bot's profile,
  username, PIN or privacy settings, which everyone sees. Ask before making
  any change on a server.
- **Deployment isn't `git push`.** `tools/build-image.sh` builds the image,
  and the owner's own untracked helper deploys it; `deploy/` holds examples
  for others, which run the published `docker.io/jodab/nejomibot:latest`.
- **Two setup guides.** The README's Getting started and `DOCKERHUB.md`, the
  image's page on Docker Hub, which each release publishes there, walk
  through the same steps: change them together. DOCKERHUB.md describes the
  code as it will be released, and uses absolute links only, since Docker
  Hub can't follow the repository's relative ones; it must stay under
  25,000 bytes.
- **Documentation style** (the owner's request, 2026-10-24): the Markdown
  files are written in clear, professional English that is easy to follow:
  complete sentences, American spelling, consistent terms (direct chat,
  group, admin, allowed list, timer, special), the reader addressed as
  "you", and every fact exact. Keep the headings that other pages link to
  (the README's anchors are used by DOCKERHUB.md and by the README itself).
- **Photo times.** Captions show every time in the bot's `timezone`, wherever
  the photo was taken. `photos.exif_datetime` works out the moment in this
  order, which must stay: a DateTimeDigitized that is a time-zone shift away
  from DateTimeOriginal (DateTimeOriginal is then in UTC), otherwise the
  offset tag, otherwise `photos_timezone`.
- **Attachments stay ignored** (the owner's decision, 2026-10-17):
  signal-cli-rest-api runs with `JSON_RPC_IGNORE_ATTACHMENTS=true`, so
  `/avatar` can't receive a picture; anyone who wants it enables attachments
  themselves. `/avatar` stays as it is.
- `TODO.md` holds what remains of the 2026-10-17 review, the owner's open
  decisions, the requests to upstream projects, and plans that are waiting,
  such as accounts without a phone number.

## Development commands

```sh
uv sync                                    # .venv with all dependencies (Python 3.14)
uv run pytest                              # every test, about 6 s; none reaches a real service
uv run pytest tests/test_timers.py         # one file
uv run pytest tests/test_timers.py::test_parse_when   # one test (or -k PATTERN)
uv run ruff check                          # lint
uv run ruff format                         # format (ruff, not Black)
uv run pyright                             # type check, strict
shellcheck tools/*.sh                      # the shell tools; CI runs it, the build doesn't
tools/translations.sh                      # after changing any message (needs GNU gettext)
tools/build-image.sh                       # test stage first, then the amd64, arm64, arm/v7 image
tools/release.sh patch                     # a release, once CI has passed; patch only until 1.0; see --help
uv run nejomibot-timers                    # the timers from a terminal, as in the image
```

`tools/build-image.sh` runs ruff check, ruff format --check, pyright and
pytest in the Dockerfile's test stage, and builds nothing if they fail. That
stage runs only for the building machine's platform. On linux/arm/v7,
Pillow and pillow-heif have no wheels, so the build stage compiles them
against Debian's libraries (`TARGETARCH` is `arm`). Debian's libheif reads
HEIF but can't write it, which only the tests do. Before pushing, the script
runs each platform's image and stops unless Python there reports that
platform's machine: Podman 4.9 built 0.94.0's images all for amd64, because
the uv stage names its own platform (`$BUILDPLATFORM`), so the image jobs
run on `ubuntu-26.04`, with Podman 5. The image is tagged with the version in
`pyproject.toml`, and `--source URL` labels it with the repository, as
ghcr.io expects. On GitHub, `.github/workflows/` has CI (checks, ShellCheck,
image build) and a release workflow, which runs only when a release is
published: it pushes to ghcr.io, and to Docker Hub when the repository has
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, attests each image's build
provenance (keyless, through `--digests`), and then makes DOCKERHUB.md the
Docker Hub page (the token needs read, write and delete scope). Dependabot
updates uv.lock, the Dockerfile's digests and the actions. Changes go in
`CHANGELOG.md`, under `## Unreleased`, which `tools/release.sh` turns into
the release's section and notes. The script releases only what CI has
passed, puts everything back if it fails before the push, and after a
failure past that point, running it again publishes the version that was
pushed. Published releases stay: a broken release gets a fixed release.

Running the bot requires a reachable signal-cli-rest-api and a `config.toml`
(made from `config.example.toml`):

```sh
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DEBUG=1 uv run nejomibot
```

Debug mode talks only to `debug_group` and the admins, and keeps its files
in a private temporary folder, created anew at each start. Stop the
production bot first: two bots on one account compete for incoming
messages.

## Architecture

**Startup** (`bot.main`): first the settings (`config.py`, with
pydantic-settings: TOML from `NEJOMIBOT_CONFIG` or `./config.toml`,
overridden by `NEJOMIBOT_*` environment variables; `extra="forbid"`, so a
renamed or removed setting in the file stops the bot with a message, while
pydantic-settings ignores an unknown environment variable). Then
`wait_for_account()` polls signal-cli-rest-api until it has the account,
answering the container health check in the meantime (`rest.accounts()`
reads `/v1/accounts` in either format upstream uses: by number before its
commit 787d204e of 2026-10-22, and as `{"number", "aci"}` since then). Next
come `SignalBot`, the outbox (with the messages kept from the previous run),
the allowed list, the handlers, the timers and the health checks; then
`bot.start()` runs signalbot's event loop and its APScheduler, and signalbot
takes over SIGTERM. Once it returns, `bot.shutdown()` cancels the bot's own
tasks, keeps the waiting messages, and closes the HTTP session and the loop.
Scheduled jobs that must not be skipped when late have
`misfire_grace_time=None`. There are two event loops, one after the other:
nothing bound to a loop (the HTTP session, locks, tasks) may pass from
`wait_for_account()`'s loop to signalbot's, which is why the wait closes the
session it used.

**Who may use what** (`bot.handlers`, `access.py`): everyday commands are
registered for every chat with `access.permits` as their filter, checked for
each message (admins and allowed contacts in direct chats; groups on the
allowed list). Admin commands are registered for direct chats only, with
`access.from_admin` as their filter, also checked for each message: the
configuration's `admins`, plus those they add with `/admin add`
(`admins.py`), which `access.admin_list` keeps in `data_dir/admins.txt` as
an `AllowedList` of Signal IDs only (the owner's decision, 2026-10-19: a
phone number can change hands). Only the configuration's admins can add and
remove admins (`is_config_admin`), and the notices, the timers and the
greeting remain theirs. `/admin add <who> [<language>]` sends the new admin
a welcome message (`admins.welcome_text`, which uses `/help`'s own lines for
a few commands) in their language, or in the language given, which it makes
theirs (`languages.set_language`), and the reply says what became of the
welcome (`Outcome`). `/delete` is registered everywhere (in debug mode, in
`debug_group` only) with the same filter, and checks for an admin again
itself; in groups, it accepts nothing after it, since `/delete list` and
`/delete 2,5,11` show and delete what the bot sent to every chat.
`incoming.inbox`, registered separately for every direct chat, keeps what
anyone other than the admins writes, for the admin command `/incoming`.
`greeting.greeter`, registered the same way, greets people on the allowed
list who write anything that `commands.known()` doesn't recognize, once a
day each, naming the bot and the first admin. The allowed list is
`data_dir/allowed.txt`, and the added admins are in `data_dir/admins.txt`;
each file is reread when it changes, at most every 2 seconds.

`/contacts` and `/trust` share one numbering (`contacts.sections`), and keep
the order each admin was shown last (`contacts.shown`: phone numbers and
Signal IDs only, and not for timers): a number in place of `<who>` in
`/contacts`, `/trust`, `/contacts add`, `/allow` and `/admin add` refers to
one of them (`contacts.find_one`), while `/birthday add` takes numbers as
chats. People are shown as `Alice (+46701234567)`, or otherwise as
`Alice (@alice.42)`: `access.names()` returns `Names`, by number, Signal ID
and group ID, with signal-cli's names taking precedence over the lists'
notes, and with `numbers` and `usernames` by Signal ID; `Names.of()` words
one person. signal-cli knows a username only for someone it found by that
username (`u:name.42` as a recipient), since Signal shares none.
`/contacts add u:name.42 <name>` (or `@name.42`) is how the bot learns one,
through `rest.name_contact`, because signalbot hands signal-cli a bare
username, which signal-cli reads as a phone number. A profile name
(`Profile.given_name`, `lastname`) is what people call their Signal name; it
isn't a username. signal-cli knows people who don't share their number by
their Signal ID alone, so a number on the lists matches neither their name
nor their direct messages: `access.link()` looks such numbers up through
signal-cli-rest-api's search (Signal's contact discovery, which is
rate-limited, so each number is looked up at most once per run,
`looked_up`), and signal-cli keeps each number it finds with its Signal ID.
This happens at startup (`link_lists`, which then writes the known names
after the lists' empty `#`) and when `/allow` adds a number. `fetch_account`
leaves out the bot's own safety number.

**Commands and aliases** (`commands.py`): every handler is a
`commands.Handler` that lists its `Command`s: the English name, whether more
text may follow it, and whether timers and `/run` may run it. Every name the
bot comes with, the languages' names included, starts with `/` (the tests
check this); only the configuration's aliases and the albums' shortcuts may
be plain words. The base class replaces an alias with the English command
(the albums' shortcuts, through `Handler.shortcuts()`, see Photos; the bot's
own aliases, `commands.ALIASES`: `/test`, `/time`, `/safety` and `/day`; the
language's names in `locale/<language>.toml`; and the configuration's
`aliases`, each taking precedence over those before it) and calls
`handle()`, which mostly calls `answer()`: logging, the read receipt, the
typing indicator for slow commands, a plain or styled reply, failures as
`error_text()`, and edits ignored where running again would do something
twice (see Conventions). `commands.known()` finds any command, the admins'
own specials included (through `Specials.takes`); timers and `/run` use it,
so the `timers` flag alone decides what timers may run.
`commands.built_in()` finds only the commands the handlers list. The alias
check uses it (so the specials file can't stop the bot from starting), and so
does the check of a special's parts (so reading that file never recurses). A
new command goes into its module, `bot.handlers()`, `help.py` and the
README's tables; the tests catch a missing registration, help line or README
row. It gets a name in each language's `locale/<language>.toml`, unless the
English name is close to that language's word or already common in it
(`/ping`, `/chats` and `/special` in Swedish), or the word already names
another command (Greek's `/γενέθλια` is `/birthdays`, so `/birthday` has no
Greek name). The words that may follow a command to say what it does, its
subcommands (`add`, `remove`, `list` and so on), are listed in
`Command.subcommands`; `canonical()` replaces the language's words for them
(`[words]` in the TOML file, such as `lägg till`) right after the command,
so handlers read English, and the timers and specials files store English.

**Sending** (`messages.py`): handlers answer through `reply()`, which goes
through `send()` to the `Outbox`. Each chat's messages go out in order;
sends that certainly failed are retried for `send_retry_hours`, with a note
that they are late (every half hour while Signal rate-limits the bot); and a
`SentLog` keeps the sent messages for `/delete`, with how each one begins,
for `/delete list`. A message that has waited 30 seconds gets a file of its
own in `data_dir/outbox` (deleted once it is sent or dropped), every waiting
message gets one at shutdown, and the files are loaded at startup. `send()`
returns the `Outcome`, which `/msg` and `/run` report. While a timer, `/run`
or a special runs a command, the `collected` ContextVar gathers its replies
instead of sending them, and `mark_read` and `show_typing` do nothing. A
`PerChat` message has a text of its own for some chats, as `/today`'s does
for the groups of people with a birthday: `send()` gives each chat its own
text, so timers, `/run`, specials and replies all do. When Signal starts
rate-limiting the bot, the outbox calls `on_rate_limited` (notices.py), and
with each message sent, `on_sent` (delivery.py). Long messages need nothing
from the bot: signal-cli (0.11.5 and later) sends a text over 2,000 UTF-8
bytes as Signal's apps do, with its beginning as the body and the whole text
as a text attachment, and (0.14.0 and later) hands the bot the whole of a
long message it receives, whether attachments are ignored or not.

**Timers** (`timers.py`): stored in `data_dir/timers.txt`, which
`nejomibot-timers` (`timers_cli.py`, reusing timers.py) also edits; reread
every 30 seconds and before each change. A run passes each command through
the real handlers as a made-up direct message from the first admin, or from
the bot's own account if there are no admins (`Timekeeper.answers_to`; for
`/run`, from the admin who sent it, so its numbers are that admin's), then
posts the collected answers to every chat of the timer. Commands that change
timers, specials, birthdays, albums or who may use the bot, that post
elsewhere (`/msg`, `/run`), or that answer for their own chat can't run from
timers (`Command.timers`); commands that only list something can, wherever
the admins post them (the owner's decision, 2026-10-21). `/timers` and
`/specials` on their own only list, while with more after them they change
things, so each has a second `Command` of the same name with `timers=False`.
A list shown under `collected` doesn't change the numbers that an admin's
`/incoming 4` or `/delete 3` uses (their `shown`); the same holds for
`contacts.remember()`.

**Specials** (`specials.py`): the admins' own commands that post several
things in order, stored in `data_dir/specials.txt` (`/special add|remove`,
`/specials`): parts made of text and a command, each run through
`Timekeeper.answers_to` as a timer's command is, with the text heading the
command's first answer. Parts are separated by `;` or line breaks, or joined
by a `+` standing on its own (`SEPARATOR`, `Part.joined`), which posts
everything the joined parts answer in one message (`by_message()`, and
`joined()`, which also heads an answer with its text). The `+` was chosen
over the `|` the owner suggested (2026-10-24), since the file uses `|` after
the name and `||` for spoilers. None of the specials are code: `/dailypost`
and `/dailyquote` were removed, as specials post the same (the owner's
decision, 2026-10-23), the daily post through `/today + /weather` and
`/uniquephoto` (the round of photos not yet sent; see Photos). A special's
parts can't be the admins' own specials, nor commands that timers can't run,
and a special that a timer runs can't be removed. `OwnSpecials.current()`
stats the file at each lookup and rereads it when it has changed. The texts
keep the formatting given in Signal (`DataMessage.text_styles`), which
`styles.marked()` writes as signal-cli-rest-api's marks and checks by
reading them back the way its parser does (`styles.unmarked()`).

**Photos** (`photos.py`, `albums.py`): each folder directly inside
`photos_dir` is an album (the owner's decision, 2026-10-23: not its
subfolders, which belong to it), named in any letter case by the longest
album name that the text after a command starts with (`album_named`).
`/uniquephoto [<album>]` is the round, which replaced `/photo new` (the
owner's decision, 2026-10-23; the timers and specials that ran it are the
owner's to change, as the changelog says): `sent-photos.txt` lists the sent
photos by their paths in the library, and an album's round starts over when
its lines are removed. `library_name()` and `album_of()` strip the prefix as
text, because pathlib's `relative_to()` made a pick take 53 ms longer for
7,641 photos. `moments()` is the single index of when each photo was taken,
for `/photo <date>`, `/albums` and `/onthisday`. `/photo <date>` is as exact
as it is given (the owner's decision, 2026-10-23): a year, month, day or
hour (`Period`) gives a random photo from that period, or else from the
nearest period of the same size that has photos; to the minute, the photo
taken closest. Every photo command accepts an album, and without one, uses
every photo, in an album or not (the owner's decision, 2026-10-23). Each
album's birth date and shortcuts are in `albums.txt`
(`photos.album_settings`), set with the admins' `/album`;
`photos_birth_date` applies to albums without one. A shortcut is an alias
for `/photo <album>`, in place of the configuration's aliases for `/photo`
(the owner's decision, 2026-10-23): `Photo.shortcuts()` hands them to
`commands.aliases()`, where every other alias takes precedence, and
`check_aliases()` leaves them out, so the file can't stop the bot from
starting. A line with a shortcut that is a command can't be read
(`parse_album_settings`), and `/album` refuses any name the bot already
responds to, just as `/special add` refuses shortcuts.

**Birthdays and holidays** (`birthdays.py`, `holidays.py`): `/today`
(`today.py`, or `/day`) describes the day, without the weather, which a
daily post adds with `/weather` (the owner's decision, 2026-10-23). On a day
with nothing, it says "Nothing special today." only when asked in a direct
chat (`day_message(asked=True)`), and nothing in a group, nor in what a
timer, a special or `/run` posts (the owner's decision, 2026-10-24), since
`send()` sends nothing when a message has nothing in it (a `PerChat` with no
text for the chat). `/today preview` shows the admins what each group gets.
The holidays, shown in every chat, come from rules in `holidays.py` (Easter
from dateutil), for 35 countries by their ISO codes (`config.Country`, which
a test keeps equal to `holidays.COUNTRIES`); the birthdays and name days of
the people a group is for are shown in that group only, never in a direct
chat (the owner's decision, 2026-10-19). Only Sweden's and Greece's names are
marked for translation (the owner's decision, 2026-10-19); the other
countries use those names, as plain strings, for the days they share with
them, so such a day appears once, translated, and only where it means the
same (Ireland's May bank holiday isn't May Day). Their public holidays were
checked against python-holidays, which isn't a dependency, for 2026 to 2045.
A contact's birthday is stored by Signal ID and phone number, is shown in the
groups they are in, and names them by their name in the contacts
(`Contact.saved_name`) at the time; the birthday of someone not on Signal is
shown in the groups given, or in every group.

**Reminders and lists** (`reminders.py`, `lists.py`): each chat's own, for
everyone allowed. A job at the start of every minute posts the reminders
that are due, after removing them from the file, so none is posted twice.
Timers can't run these commands, nor the birthday lists, since they answer
for their own chat.

**Notices** (`notices.py`): the admins are told of each start, once the bot
is ready, in one styled message (`start_text`): the version and how long the
start took, then what needs their attention (an update, a stop that wasn't
clean, unreadable lines in the bot's files, failed checks, waiting
messages), then how the bot is doing, reusing the functions of `/status` and
the health checks. This happens at most once per `QUIET` (10 minutes),
except after an update (the owner's decision, 2026-10-23): a start within
that time waits until it has passed (`Notices.delay`), and
`data_dir/run.json` records when the admins were last told (`Run.told`),
alongside each run's start and clean stop. The admins are also told when
Signal starts rate-limiting the bot (tried once, `Outbox.try_once`), and of
changed safety numbers, which are checked every `healthcheck_minutes`.

**Delivery** (`delivery.py`): signalbot drops receipts (2.1.3), so
`rest.received()` opens a websocket of the bot's own alongside signalbot's,
since signal-cli-rest-api sends everything to every websocket in json-rpc
mode; `receipt_in()` parses only what contains `"receiptMessage"`. A receipt
marks `Sent.confirmed` in the outbox's `SentLog` (by Signal ID, with whether
the message was read), so receipts are kept as long as `/delete`'s day.
`on_sent` checks each message 10 minutes later, and logs a warning when
nobody has confirmed it, unless the websocket wasn't open for that whole
time (`Receipts.since`). `/delivery` lists `delivery_messages` of the log,
with delete.py's line for each message.

**Beyond signalbot**: `rest.py` (direct requests) and `account.py` (pydantic
models for contacts, safety numbers and devices; `Account` looks people up
through indexes). signalbot drops signal-cli-rest-api's error text, so
`messages.describe()` words what remains: the HTTP status. Every request the
bot makes itself, rather than through signalbot (rest.py, OpenWeatherMap,
the exchange rates, RIPEstat, the health check URL), shares one aiohttp
session, `client.py`. aiohttp's error text can contain the URL, with the
OpenWeatherMap key or a phone number in it: word such errors with
`describe()` or `web_error()`, never with `str(e)`.

**Health** has two layers. `health.py` runs checks (signal-cli-rest-api
through signalbot, the bot itself, and Signal's servers through the linked
devices) every `healthcheck_minutes`, logs failures, and pings
`healthcheck_url` with the results, followed by the versions, uptime, memory
and backups (`ping_text`). `/status` shows the same through the same
functions, which live in `health.py` because `status.py` imports it. The
container check (`healthcheck.py`, the image's HEALTHCHECK) asks the running
bot over the abstract Unix socket `\0nejomibot-health`. It checks liveness
only: it fails when the bot doesn't answer or its rounds are late, never
because Signal or signal-cli-rest-api fails (a restart wouldn't help, and
could lose the messages that have waited less than half a minute, which
aren't on disk yet), and not while the bot waits for the account.

**Files the bot keeps**: `allowed.txt`, `admins.txt`, `timers.txt`,
`specials.txt`, `reminders.txt`, `lists.txt`, `birthdays.txt`, `albums.txt`,
`languages.txt`, `sent-photos.txt`, `run.json` and `outbox/` in `data_dir`,
written through `files.write_privately` (mode 0600, a `mkstemp` temporary
file, fsync, replace, then an fsync of the folder; `replace_privately` for
any writer) or `files.append_privately`. In the line-based files, hand
edits, comments and unreadable lines are kept as they are; a new file of
this kind uses `files.KeptLines`, as the reminders, lists and birthdays do.
Debug mode keeps the files in a private temporary folder per run.

**Backups** (`backups.py`): every day at `backups_at` in `timezone`, and at
startup if none is from the last day, the bot writes a `tar.zst` of every
file in `data_dir` except `run.json` (and the outbox, which is a folder, and
files over 10 MB), plus the configuration file and `config.example.toml` from
the working directory, through `replace_privately` in a thread, into
`settings.backups_folder` (`backups_dir`, otherwise `data_dir/backups`),
keeping the newest `backups_kept`. It makes none when the files' contents
match the latest backup (a SHA-256 of each, with the latest backup
decompressed for the comparison), which `unchanged_at` records, in memory,
so that the backups count as current. tarfile and zstd are part of Python
3.14; entries are built from `os.fstat`, because `tar.add` looks up owner
names, which loads NSS libraries for good (0.7 MB). `backups.state()` feeds
`/status`'s Backups check (which fails when the last backup failed, or when
the backups haven't been current for two days) and the health ping's line.
No backups are made in debug mode, or with `backups = false`.

**Translations** (`i18n.py`): messages are written in English, marked with
`_()`, `ngettext()`, or `N_()` in tables built ahead of use, and formatted
after translation: `_("Weather in {city}").format(city=...)`. The
Dockerfile's `translations` stage compiles each `locale/*.po` (Swedish,
Greek) to a `.mo` file with polib (the `translations` dependency group), and
the image gets only the `.mo` files, which the bot reads with gettext
(`i18n.catalog`); from a checkout without `.mo` files, it compiles the `.po`
files with polib, available there through the dev group. `.mo` files stay
out of git. `tests/test_i18n.py` fails on an untranslated, fuzzy or obsolete
message, or on differing `{fields}`: after changing messages, run
`tools/translations.sh` and translate `sv.po` and `el.po` (Greek since
2026-10-23: serious, not silly or chatty, as the owner asked). Each chat may
have a language of its own (`languages.py`, `/language`, stored in
`languages.txt` by `i18n.chat_languages`; a group's language is an admin's
to set, and other chats' languages are set by their `/chats` numbers, the
owner's decisions of 2026-10-23): `language()` reads the `speaking_now`
ContextVar, which `commands.Handler.handle_data_message` sets from the chat
(`messages.language_here`), so `_()` follows it and handlers need no
changes. What the bot sends on its own sets the language for each chat:
`Timekeeper.post` (timers and `/run`), reminders, the greeting, the notices
(`notices.worded`, once per language among the admins) and the outbox's
notes. `Timekeeper.post` runs each command once per language among its
chats, every run drawing from one `messages.Draw`, whose `chance()` all
random picks use, and whose `used` keeps a photo that one run marked as sent
unsent for the other languages' runs: every chat gets the same photo, and
the round uses up only one. The bot accepts every language's command names
and words from anyone (`every_language()`, `names_of()`, from the `.toml`
files alone, so a language's catalog loads only once the bot speaks that
language: 189 KB for Swedish); a test checks that no name stands for two
different things. Weather descriptions come from the bot's own translated
table, so the cached weather serves every language; a place keeps its names
in the bot's languages (`weather.Place.names`).

## Conventions

- Handlers never raise: `answer()` posts failures with
  `messages.error_text()` ("Something went wrong: …") and logs them with
  `messages.log_failure()`: an expected failure (a file or service failing)
  in a single line, a bug with its traceback.
- The log says what happened and where, not who was involved: INFO has
  command names and the kind of chat (`chat_kind`, `to_whom`), never phone
  numbers, Signal or group IDs, or message text; those go at DEBUG.
  `log_level` sets the bot's own level, and every library logs at WARNING
  through the same handler.
- Styled replies (`TextMode.STYLED`) need `messages.escape()` on any text
  from outside, such as names and errors; a special's texts are already in
  marks.
- An `EditMessage` is a `DataMessage`, and `answer(edits=...)` says what an
  edit does (`commands.Edits`): `RUN_AGAIN`, for commands that show
  something or set a value (`/name`, `/trust`); `REPLACE`, for those that add
  or remove something, which say how to undo it with `undo_with()` (or
  `cannot_undo()`), so that an edit undoes what its message did, then runs;
  `NOT_RUN`, for posts and deletions, which says so; and `IGNORE`, for
  `/delete` alone. What a command did is kept by its message (sender and
  timestamp) for a day, in memory, and an edit's effect is also kept under
  its own timestamp, because Signal Desktop names the latest edit while other
  clients name the first message; an edit of a message from before the start
  isn't run. A new command that changes something uses `REPLACE` and
  registers its undo; `KeptLines` changes provide one (`revert`).
- signalbot's logger stays at WARNING: at INFO, it logs every message the
  bot receives, in full.
- Python 3.14 only: the code uses `except A, B:` without parentheses
  (PEP 758) and `type` aliases.
- Tests: `tests/conftest.py` gives each test fresh settings
  (`get_settings.cache_clear()`), a fresh allowed list, specials, reminders,
  lists, birthdays and debug folder, points `signal_service` at
  `127.0.0.1:1`, closes the HTTP session, and imports `nejomibot.bot` so
  that every handler is known; its `answers` fixture keeps what commands
  answer. `tests/helpers.py` has the made-up people and groups,
  `message_from`, `make_jpeg` and `FakeApi`, a stand-in signal-cli-rest-api
  (import from there, not from conftest); the `bot` fixture is a real
  signalbot running against it. Deprecation warnings fail the tests. All test
  data is made up.
- Comments and docstrings are short, plain sentences that say what something
  does and why; module docstrings explain the feature as an admin uses it.

## Resource budget

- **2026-10-18:** about 73 MB peak RSS after the imports, the Swedish
  translations and one picture opened (70 MB with `photos_heif = false`;
  mostly signalbot, aiohttp and pydantic; runs vary by about a megabyte),
  and a 232 MB image (amd64; arm64 250 MB, arm/v7 202 MB), with
  phonenumberslite in place of signalbot's phonenumbers
  (`exclude-dependencies` in pyproject.toml). Measure both when adding a
  dependency.
- **2026-10-19:** reminders, lists, birthdays, holidays, notices,
  `/forecast` and `/onthisday` added 0.6 MB (73.9 to 74.5 MB, measured the
  same way), and no dependency; `/onthisday` keeps about 300 bytes per photo
  once used.
- **Later on 2026-10-19:** added admins, numbered contacts, the safety
  numbers, the backups and the holidays of 35 countries took 0.5 MB more of
  Python's allocations after the imports and the Swedish translations
  (tracemalloc, 33.6 to 34.1 MB; RSS the same within its noise, 77.3 to
  77.6 MB with a 1024×768 picture), of which the holiday tables account for
  0.3 MB and tarfile for 0.36 MB. The first backup keeps 0.8 MB more, and the
  first comparison with the latest backup (which decompresses it) another
  0.8 MB, both reused afterwards rather than growing: these are zstd's
  buffers, which glibc keeps, and a run peaks 1 to 3 MB higher. The window
  size changes neither figure. No dependency was added: tarfile and zstd
  are part of Python 3.14, and present in the image on all three platforms
  (libzstd 1.5.7).
- **2026-10-23, albums:** the single index of when photos were taken
  (`photos.moments`, for `/photo <date>`, `/albums` and `/onthisday`) keeps
  401 bytes per photo, 3.06 MB for 7,641 photos (tracemalloc, once the
  command's library has been released; a datetime takes 16 bytes more than
  the date it replaced), and peaks at 11 MB while it is first read, which
  takes 2.4 to 2.8 s on a desktop computer. A `/uniquephoto` pick's
  bookkeeping takes 32 ms for 7,641 photos, listing included, since
  `library_name()` stopped using pathlib's `relative_to()` (which accounted
  for 53 ms of it before). Languages: an English bot reads only Swedish's
  names, 146 KB with the first TOML read, and loads the Swedish catalog,
  189 KB kept (368 KB at its peak, from the .mo file), only once a chat
  speaks Swedish.
- **2026-10-23, every dependency updated** (signalbot 2.1.3, python-dateutil
  3.0.0, Python 3.14.9): 78.5 MB peak RSS against 78.8 MB before, the median
  of five runs each (77.5 to 79.3 MB: noise), and a 235.6 MB image (amd64),
  as before.
