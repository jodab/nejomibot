# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

nejomibot is a Signal bot for a family or a group of friends: a daily post
(weather and a photo of the day), a few everyday commands, and admin commands
in direct chats. It talks to Signal through signalbot, which talks to
signal-cli-rest-api in json-rpc mode. It ships as a container image.

## The owner's instructions

From the owner of the project, in no order of priority:

1. Never change any of the bot's user-facing functionality unless
   specifically asked to. If a change becomes necessary, ask what to do.
2. Keep the code easy to understand and maintain, and reliable, stable,
   secure and privacy-respecting. Keep this in mind for any code or function
   written or considered. Bonus points for less and smaller code, and for
   reusing code and functions as much as possible, as long as that doesn't
   come at the cost of the other instructions.
3. Always follow the best known practices and standards in any decision for
   this project. That includes bot behaviour, container maintenance, startup,
   restarts and shutdown, error reports, health checks, logging, Python,
   linting, unit tests, Podman, systemd interactions: essentially all of what
   this project does.
4. Keep memory and resource use low: light enough that the project can be
   hosted on free or essentially free services online.
5. Do our very best not to hit rate limits on Signal's servers.
6. Make the bot as performant as possible, reducing latency wherever we can.
   Performance and low resource use (4, 7) are both highly important; when
   they pull against each other, performance is slightly favored.
7. Keep the final image as small and light (RAM, CPU, disk) as possible:
   only what is strictly necessary goes in it.
8. Use minimal resources to build the images, as well.
9. Measure, test and verify any changes, for accuracy and future improvements.

User-facing means anything people in Signal see or can do: the commands and
their names, the replies and their wording, who may use what, and what is
posted where and when. When unsure whether a change is user-facing, ask.

## Working agreements

- **Standards first.** Prefer the established convention (OCI/Docker, Python
  packaging, systemd/Quadlet, shell). When something is only a local
  convenience or deviates from the norm, say so and name the standard
  alternative.
- **signalbot first.** Talk to Signal through signalbot's public API for
  everything it can do; check newer signalbot releases before going around
  it. Direct signal-cli-rest-api requests live only in `nejomibot/rest.py`,
  each function saying in a comment what signalbot lacks.
- **The repo is meant to go public.** No real names, phone numbers, group IDs,
  dates, places or hostnames in tracked files, tests and docs included. Use
  made-up values (`+4670000000x`, `group.ZmFtaWx5`, Alice and Bob, Stockholm
  and Helsinki); personal values belong in the untracked `config.toml`. Don't
  rewrite git history unless asked.
- **Commits.** Commit or push only when asked. Commits are signed; if signing
  doesn't work from the session, leave the commit to the owner.
- **The live Signal account.** When testing against it, send only to the
  group set aside for testing, prefer read-only requests and
  `signal-account.sh --dry-run`, and ask before changing the bot's profile,
  username, PIN or privacy, which everyone sees. Ask before any change on a
  server.
- **Deployment isn't `git push`.** `tools/build-image.sh` builds the image and
  the owner's own untracked helper deploys it; `deploy/` holds examples for
  others, which run the published `docker.io/jodab/nejomibot:latest`.
- **Two setup guides.** The README's Getting started and `DOCKERHUB.md`, the
  image's page on Docker Hub, which each release puts there, walk through
  the same steps: change them together. DOCKERHUB.md describes the code as
  it will be released, and has absolute links only, as Docker Hub can't
  follow the repository's relative ones; it must stay under 25,000 bytes.
- **Photo times.** Captions show every time in the bot's `timezone`, wherever
  the photo was taken. `photos.exif_datetime` works the moment out in this
  order, which must stay: a DateTimeDigitized a time-zone shift away from
  DateTimeOriginal (DateTimeOriginal is then UTC), else the offset tag, else
  `photos_timezone`.
- **Attachments stay ignored** (the owner's decision, 2026-10-17):
  signal-cli-rest-api runs with `JSON_RPC_IGNORE_ATTACHMENTS=true`, so
  `/avatar` can't take a picture; whoever wants it enables attachments
  themselves. `/avatar` stays as it is.
- `TODO.md` holds what's left of the 2026-10-17 review, the owner's open
  decisions and the upstream asks, and plans that wait: accounts without a
  phone number, and text styles in posts.

## Development commands

```sh
uv sync                                    # .venv with all dependencies (Python 3.14)
uv run pytest                              # every test, about 4 s; none reaches a real service
uv run pytest tests/test_timers.py         # one file
uv run pytest tests/test_timers.py::test_parse_when   # one test (or -k PATTERN)
uv run ruff check                          # lint
uv run ruff format                         # format (ruff, not Black)
uv run pyright                             # type check, strict
shellcheck tools/*.sh                      # the shell tools; CI runs it, the build doesn't
tools/translations.sh                      # after changing any message (needs GNU gettext)
tools/build-image.sh                       # test stage first, then the amd64, arm64, arm/v7 image
tools/release.sh patch                     # a release (or minor, major), once CI passed; see --help
uv run nejomibot-timers                    # the timers from a terminal, as the image has it
```

`tools/build-image.sh` runs ruff check, ruff format --check, pyright and
pytest in the Dockerfile's test stage and builds nothing if they fail. That
stage runs on the building machine alone. On linux/arm/v7 Pillow and
pillow-heif have no wheels, so the build stage compiles them against Debian's
libraries (`TARGETARCH` is `arm`). Debian's libheif reads HEIF but can't
write it, which only the tests do. The image is tagged with the version in `pyproject.toml`; `--source URL` labels
it with the repository, as ghcr.io wants. On GitHub, `.github/workflows/`
has CI (checks, ShellCheck, image build) and a release workflow that pushes
to ghcr.io, and to Docker Hub when the repository has `DOCKERHUB_USERNAME`
and `DOCKERHUB_TOKEN`, only when a release is published, attests each
image's build provenance (keyless, through `--digests`), and then makes
DOCKERHUB.md the Docker Hub page (the token needs read, write and delete
scope); Dependabot updates
uv.lock, the Dockerfile's digests and the actions. Changes go in
`CHANGELOG.md`, under `## Unreleased`, which `tools/release.sh` turns into
the release's section and notes. The script releases only what CI passed,
puts everything back if it fails before the push, and after a failure past
that, running it again publishes the pushed version. Published releases stay;
a broken one gets a fixed release.

Running the bot needs a reachable signal-cli-rest-api and a `config.toml`
(from `config.example.toml`):

```sh
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DEBUG=1 uv run nejomibot
```

Debug mode talks only to `debug_group` and the admins, and keeps its files in
a private temp folder, new at each start. Stop the production bot first: two
bots on one account compete for incoming messages.

## Architecture

**Startup** (`bot.main`): settings (`config.py`, pydantic-settings: TOML at
`NEJOMIBOT_CONFIG` or `./config.toml`, overridden by `NEJOMIBOT_*`
environment variables; `extra="forbid"`, so a renamed or removed setting in
the file stops the bot with a message, while pydantic-settings ignores an
unknown variable) → `wait_for_account()` polls
signal-cli-rest-api until it has the account, answering the container health
check meanwhile → `SignalBot` → outbox (with the messages kept from before),
allowed list, handlers, timers, health → `bot.start()` runs signalbot's event
loop and its APScheduler, and signalbot takes over SIGTERM. Once it returns,
`bot.shutdown()` cancels the bot's own tasks, keeps the waiting messages,
closes the HTTP session and the loop. Scheduled jobs that must not be skipped
when late have `misfire_grace_time=None`. These are two event loops, one
after the other: nothing bound to a loop (the HTTP session, locks, tasks)
may go from `wait_for_account()`'s to signalbot's, which is why the wait
closes the session it used.

**Who may use what** (`bot.handlers`, `access.py`): everyday commands are
registered for every chat with `access.permits` as filter, checked for each
message (admins and allowed contacts in direct chats; groups on the allowed
list). Admin commands use signalbot's contact filter with `settings.admins`,
so they answer in direct chats only. `/delete` is registered everywhere (in
debug mode, in `debug_group`) and checks for an admin itself in groups.
Admins exist only in the config; the allowed list is `data_dir/allowed.txt`,
reread when it changes.

**Commands and aliases** (`commands.py`): every handler is a
`commands.Handler` that lists its `Command`s: the English name, whether more
may follow it, whether timers and `/run` may run it, and hidden names it has
always had (`/test`, `/time`...). Every name the bot comes with, the
language's too, starts with `/` (tests check); only the config's aliases may
be plain words. The base class replaces an alias (the config's `aliases` and
the language's names in `locale/<language>.toml`) by the English command and
calls `handle()`, which mostly calls `answer()`: log, read receipt, typing
for slow ones, reply plain or styled, failures as `error_text()`, and edits
ignored where running again would do it twice (see Conventions).
`commands.known()` finds any command, the admins' own specials too (through
`Specials.takes`); timers and `/run` use it, so what timers may run is the
`timers` flag alone. `commands.built_in()` finds only those the handlers
list. The alias check uses it (so the specials file can't stop the bot from
starting), and so does the check of a special's parts (so reading that file
never recurses). A new command goes into its module, `bot.handlers()`,
`help.py` and the README's tables; tests catch a missing registration, help
line or README row. It gets a Swedish name in `locale/sv.toml`, unless the
English one is close to the Swedish word or already common in Swedish
(`/ping`, `/chats`, `/special`).

**Sending** (`messages.py`): handlers answer through `reply()`, which goes
through `send()` to the `Outbox`: each chat's messages in order, sends that
surely failed retried for `send_retry_hours` with a note that they're late
(every half hour while Signal rate-limits the bot), and a `SentLog` for
`/delete`. A message waiting 30 s gets a file of its own in
`data_dir/outbox` (deleted once sent or dropped), every waiting one at
shutdown, and they're loaded at start. `send()` returns the `Outcome`, which
`/msg` and `/run` report. While a timer, `/run` or a special runs a command,
the `collected` ContextVar gathers its replies instead of sending them, and
`mark_read` and `show_typing` do nothing.

**Timers** (`timers.py`): kept in `data_dir/timers.txt`, which
`nejomibot-timers` (`timers_cli.py`, reusing timers.py) edits too; reread
every 30 seconds and before each change.
A run passes each command through the real handlers as a made-up direct
message from the first admin, or the bot's own account if there are none
(`Timekeeper.answers_to`), then posts the collected answers to every chat of
the timer. Commands that manage timers, specials or the allowed list (even
`/chats` and `/allowed`, which only list), or post elsewhere (`/msg`,
`/run`), can't run from timers.

**Specials** (`specials.py`): commands that post several things, in order.
`/dailypost` (the weather, then the photo of the day from the round) and
`/dailyquote` are code; the admins' own are data in `data_dir/specials.txt`
(`/special add|remove`, `/specials`): parts of text and a command, each run
through `Timekeeper.answers_to` as a timer's, its text heading the first
answer. Their parts can't be the admins' own specials, nor what timers can't
run; one a timer runs can't be removed. `OwnSpecials.current()` stats the
file at each lookup and rereads it when it changed.

**Beyond signalbot**: `rest.py` (direct requests) and `account.py` (pydantic
models for contacts, safety numbers, devices; `Account` looks people up
through indexes). signalbot drops signal-cli-rest-api's error text, so
`messages.describe()` words what is left: the HTTP status. Every request the
bot makes itself, not through signalbot (rest.py, OpenWeatherMap, exchange
rates, RIPEstat, the health check URL), shares one aiohttp session,
`client.py`. aiohttp's error text can hold the URL, with the OpenWeatherMap
key or a phone number in it: word such errors with `describe()`/`web_error()`,
never `str(e)`.

**Health** has two layers. `health.py` runs checks (signal-cli-rest-api
through signalbot, the bot itself, Signal's servers through the linked
devices) every `healthcheck_minutes`, logs failures and pings
`healthcheck_url` with the results, then the versions, uptime and memory
(`ping_text`). `/status` shows those through the same functions, which live
in `health.py` because `status.py` imports it. The container check
(`healthcheck.py`, the image's HEALTHCHECK) asks the running bot over the
abstract Unix socket
`\0nejomibot-health`. It is liveness only: it fails when the bot doesn't
answer or its rounds are late, never because Signal or signal-cli-rest-api
fails (a restart wouldn't help, and could lose the messages that have waited
less than half a minute, which aren't on disk yet), and not while the bot
waits for the account.

**Files the bot keeps**: `allowed.txt`, `timers.txt`, `specials.txt`,
`sent-photos.txt` and `outbox/` in `data_dir`, written through
`files.write_privately` (mode 0600, a `mkstemp` temp file, fsync, replace,
fsync of the folder) or `files.append_privately`. In the first three, hand
edits, comments and unreadable lines are kept as they are. Debug mode keeps
them in a private temp folder per run.

**Translations** (`i18n.py`): messages are English, marked with `_()`,
`ngettext()`, or `N_()` in tables made ahead of use, and formatted after
translating: `_("Weather in {city}").format(city=...)`. The Dockerfile's
`translations` stage compiles `locale/sv.po` to `sv.mo` with polib (the
`translations` dependency group), and the image gets the `.mo` alone, which
the bot reads with gettext (`i18n.catalog`); from a checkout, without a
`.mo`, it compiles the `.po` with polib, there through the dev group. `.mo`
files stay out of git. `tests/test_i18n.py` fails on an untranslated,
fuzzy or obsolete message, or on differing `{fields}`: after changing
messages, run `tools/translations.sh` and translate `sv.po`.

## Conventions

- Handlers never raise: `answer()` posts failures with
  `messages.error_text()` ("Something went wrong: …"), and logs them with
  `messages.log_failure()`: an expected one (a file or service failing) in
  a line, a bug with its traceback.
- The log says what and where, not who: INFO has command names and the kind
  of chat (`chat_kind`, `to_whom`), never phone numbers, Signal or group IDs,
  or message text; those go at DEBUG. `log_level` sets the bot's own level;
  every library logs at WARNING through the same handler.
- Styled replies (`TextMode.STYLED`) need `messages.escape()` on any text from
  outside, such as names and errors.
- An `EditMessage` is a `DataMessage`, so an edit runs its command again,
  which is wanted wherever that works: commands that show something, or set
  a value (`/name`, `/trust`), so the edit applies the correction. Those
  that would do it twice, such as adding a timer or someone to the allowed
  list, deleting, or posting elsewhere, pass `answer(edits=False)` and
  ignore edits.
- signalbot's logger stays at WARNING: at INFO it logs every message the bot
  receives, in full.
- Python 3.14 only: the code uses `except A, B:` without parentheses (PEP 758)
  and `type` aliases.
- Tests: `tests/conftest.py` gives each test fresh settings
  (`get_settings.cache_clear()`), a fresh allowed list, specials and debug
  folder, points `signal_service` at `127.0.0.1:1`, closes the HTTP session,
  and imports `nejomibot.bot` so every handler is known. `tests/helpers.py`
  has the made-up people and groups and `FakeApi`, a stand-in
  signal-cli-rest-api (import from there, not from conftest); the `bot`
  fixture is a real signalbot against it. Deprecation warnings fail the
  tests. All test data is made up.
- Comments and docstrings are short, plain sentences saying what something
  does and why; module docstrings explain the feature as an admin uses it.

## Resource budget

Measured 2026-10-18: about 73 MB peak RSS after imports, the Swedish
translations and one picture opened (70 MB with `photos_heif = false`;
mostly signalbot, aiohttp and pydantic; runs vary by a MB) and a 232 MB
image (amd64; arm64 250 MB, arm/v7 202 MB), with phonenumberslite in place of signalbot's phonenumbers
(`exclude-dependencies` in pyproject.toml). Measure both when adding a
dependency.
