# AGENTS.md

This file guides coding agents, such as Claude Code, in this repository;
CLAUDE.md imports it. It says how the project works and what it requires.
Its history is in git and CHANGELOG.md.

nejomibot is a self-hosted Signal bot for a family or a group of friends: a
daily post (the day's holidays, birthdays and name days, the weather, and a
photo of the day), everyday commands for photos, the weather, reminders and
shared lists, timers and the admins' own commands, and admin commands in
direct chats. It talks to Signal through signalbot, which talks to
signal-cli-rest-api in json-rpc mode, and it ships as a container image.

## The owner's instructions

The owner's requirements for the project, in no particular order; where they
conflict, rule 10 prevails:

1. **No unrequested changes to user-facing behavior.** Change what the bot
   does in Signal only when explicitly asked to. If such a change becomes
   necessary, ask the owner how to proceed.
2. **Maintainable, reliable and secure code.** Write code that is easy to
   understand and maintain, reliable, stable, secure and respectful of
   privacy, and weigh every change against these qualities. Less code,
   smaller functions and reuse of existing code are preferred, provided they
   cost nothing against the other requirements.
3. **Established practices.** Follow established best practices and
   standards in every decision: the bot's behavior, container maintenance,
   startup, restarts and shutdown, error reporting, health checks, logging,
   Python, linting, unit tests, and the interaction with Podman and systemd;
   in short, everything the project does.
4. **Low resource use.** Keep memory and other resource use low enough that
   the bot can run on free or nearly free hosting.
5. **Signal's rate limits.** Make every effort to stay within the rate limits
   of Signal's servers.
6. **Performance.** Make the bot as fast as possible, and reduce latency
   wherever practical. Performance and low resource use (rules 4 and 7) are
   both important; where they conflict, performance takes slight precedence.
7. **A minimal image.** Keep the final image as small and light as possible
   in memory, CPU and disk: it contains only what is strictly necessary.
8. **Lean builds.** Keep the resources needed to build the images to a
   minimum as well.
9. **Measurement and verification.** Measure, test and verify every change,
   for correctness and as a baseline for later improvements.
10. **Availability above all.** Uptime and availability come first: every
    change, push and image build must leave the bot working, stable and
    fully reliable. This rule overrides all others.
11. **Documented workarounds.** Document every workaround for a bug or
    limitation of signal-cli-rest-api as such, and check it again with later
    releases, so that it can be removed once it is no longer needed.
12. **Reuse and refactoring.** Reuse existing code wherever possible, and
    refactor wherever doing so improves the code.
13. **Latest stable releases.** Follow the latest stable release of Python
    itself and of every library, image and tool the project uses (uv.lock,
    uv, the base images, the GitHub Actions and their runners, and
    signal-cli-rest-api in `deploy/`): move to each one once it is out, but
    not to pre-releases. An upgrade that can't be made yet without breaking
    something waits (rule 10), and TODO.md says what it waits on.

User-facing means anything people see or can do in Signal: the commands and
their names, the replies and their wording, who may use what, and what is
posted where and when. When it is unclear whether a change is user-facing,
ask.

## Working agreements

- **Standards first.** Prefer the established convention (OCI/Docker, Python
  packaging, systemd/Quadlet, shell). When something is only a local
  convenience or deviates from the norm, say so and name the standard
  alternative.
- **signalbot first.** Talk to Signal through signalbot's public API for
  everything it can do, and check newer signalbot releases before going
  around it. Direct signal-cli-rest-api requests live only in
  `nejomibot/rest.py`, each function saying in a comment what signalbot
  lacks, and in `nejomibot-account` (`account_cli.py`), which manages the
  account itself, as signalbot doesn't, and runs without the bot.
- **The repository is public.** No real names, phone numbers, group IDs,
  dates, places or hostnames in tracked files, tests and documentation
  included. Use made-up values (`+4670000000x`, `group.ZmFtaWx5`, Alice and
  Bob, Stockholm and Helsinki); personal values belong in the untracked
  `config.toml`. Don't rewrite git history unless asked.
- **0.99.x until 1.0.** Every release is a patch release until the owner
  says it is time for 1.0; a minor release would be 0.100.0.
  `tools/release.sh` stops on minor and major releases, and its guard comes
  out only when the owner says so.
- **Commits.** Commit or push only when asked. Commits are signed; if signing
  doesn't work from the session, leave the commit to the owner.
- **The live Signal account.** When testing against it, send only to the
  group set aside for testing, prefer read-only requests and
  `nejomibot-account --dry-run`, and ask before changing the bot's profile,
  username, PIN or privacy settings, which everyone sees. Ask before making
  any change on a server.
- **signal-cli-rest-api runs in `json-rpc` mode**, not `json-rpc-native`,
  which has had odd bugs and has no 32-bit ARM build; the examples in
  `deploy/` use `json-rpc`.
- **Deployment isn't `git push`.** `tools/build-image.sh` builds the image,
  and the owner's own untracked helper deploys it; `deploy/` holds examples
  for others, which run the published `docker.io/jodab/nejomibot:latest`.
- **One page.** README.md is also the image's page on Docker Hub, which
  each release publishes there, and the package's on PyPI. It describes the
  code as it will be released, links only absolutely (Docker Hub and PyPI
  can't follow the repository's relative links, nor its own anchors), and
  stays under Docker Hub's 25,000 bytes; the tests check both.
- **The readers.** Whoever deploys the bot is a Linux or Unix administrator
  of average experience, at home with Python, Docker or Podman, and
  containers, who scripts a lot and programs a little. The documentation,
  the tools' help and the comments in the examples say what such a reader
  needs and no more: what, where and how, never what is obvious to them.
- **Documentation style.** The Markdown files are written in clear,
  professional English that is easy to follow: complete sentences, American
  spelling, consistent terms (direct chat, group, admin, allowed list,
  timer, special), the reader addressed as "you", and every fact exact.
  Keep the headings that other pages link to, such as `#linking-to-a-phone`
  and `#podman-quadlets`, which the README itself uses.
- **Photo times.** Captions show every time in the bot's `timezone`, wherever
  the photo was taken. `photos.exif_datetime` works out the moment in this
  order, which must stay: a DateTimeDigitized that is a time-zone shift away
  from DateTimeOriginal (DateTimeOriginal is then in UTC), otherwise the
  offset tag, otherwise `photos_timezone`.
- **Attachments stay ignored.** signal-cli-rest-api runs with
  `JSON_RPC_IGNORE_ATTACHMENTS=true`, so `/avatar` can't receive a picture;
  anyone who wants it enables attachments themselves. `/avatar` stays as it
  is. `nejomibot-chat` attaches files itself, as signalbot's
  `Attachment.base64_content`, which `/msg` posts and `/avatar` takes;
  `received_attachments` (off by default) only lists where signal-cli keeps
  received files, for `--save`, and the bot holds no copy.
- **TODO.md holds only the open work:** the owner's open decisions, plans
  that wait, what upstream projects lack (no issues are filed upstream) and
  what waits on them. What is done leaves it, for the changelog.

## Development commands

```sh
uv sync                                    # .venv with all dependencies (Python 3.15)
uv run pytest                              # every test, about 10 s; none reaches a real service
uv run pytest tests/test_timers.py         # one file
uv run pytest tests/test_timers.py::test_parse_when   # one test (or -k PATTERN)
uv run ruff check                          # lint
uv run ruff format                         # format (ruff, not Black)
uv run pyright                             # type check, strict
shellcheck tools/*.sh                      # the shell tools; CI runs it, the build doesn't
tools/translations.sh                      # after changing any message (needs GNU gettext); with a code, starts a language
tools/build-image.sh                       # test stage first, then the amd64, arm64, arm/v7 image
tools/release.sh patch                     # a release, once CI has passed; patch only until 1.0; see --help
uv run nejomibot-timers                    # the timers from a terminal, as in the image
uv run nejomibot-chat                      # the running bot from a terminal, as its first admin
uv run nejomibot-account                   # the Signal account: status, setup, profile; --dry-run sends nothing
```

`tools/build-image.sh` runs ruff check, ruff format --check, pyright and
pytest in the Dockerfile's test stage, for the building machine's platform
only, and builds nothing if they fail. The images are tagged with the
version in `pyproject.toml`, and `--source URL` labels them with the
repository, as ghcr.io expects. Before pushing, the script runs each
platform's image and stops unless Python there reports that platform's
machine: Podman 4 built every platform as amd64, so the image jobs run on
`ubuntu-26.04`, with Podman 5. In the image:

- On linux/arm/v7, Pillow and pillow-heif have no wheels, so the build stage
  compiles them against Debian's libraries (`TARGETARCH` is `arm`); Debian's
  libheif reads HEIF but can't write it, which only the tests do.
- The build stage strips the compiled modules and libraries
  (`--strip-unneeded`), then loads each one, since aiohttp, multidict, yarl
  and propcache fall back to pure Python without a word when theirs doesn't
  load.
- signalbot's phonenumbers is replaced by phonenumberslite, from the
  dependency group `lite`, which every uv sync has (`exclude-dependencies`
  in pyproject.toml); published metadata keeps phonenumbers.
- The wheel, as the image and PyPI have it, holds the translations compiled
  (`tools/compile-translations.py`), not their `.po` files
  (`wheel-exclude`).
- The final stage sets `MALLOC_ARENA_MAX=2`. The base image has no bytecode
  for the standard library, and `PYTHONDONTWRITEBYTECODE` keeps it from
  being written at run time, so the final stage imports the bot's entry
  points once to write it for what they use.
- The image's tools are the package's entry points, Python as the bot is,
  and need no shell. `nejomibot-help` (`guide.py`, which imports nothing, so
  it shows at once) is the guide every interactive shell starts with (not
  scripts or `sh -c`), and `help` too, a link in `/usr/local/bin`, as no
  shell's alias reaches `podman exec nejomibot help`. Of `tools/`, the image
  has only `nejomibot-profile.sh`, as `/etc/profile.d/nejomibot.sh`, which
  shows the guide and makes `help` an alias for it, where bash's own `help`
  would hide it: bash reads it from `/etc/bash.bashrc`, a login shell from
  `/etc/profile` (whose PATH lacks the tools, which it adds), and `sh`
  through `ENV`.
- `.dockerignore` is an allowlist: a new file for the image needs a line
  there.

`.github/workflows/` has CI (the checks, ShellCheck, the amd64 image build)
and a release workflow, which runs only when a release is published: it
pushes to ghcr.io, and to Docker Hub when the repository has
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`, attests each image's build
provenance (keyless, through `--digests`), and makes README.md the Docker
Hub page (the token needs read, write and delete scope). With the variable
`PYPI_PUBLISH` set to `true`, it also builds the wheel and sdist and
publishes them on PyPI once the images are out, by trusted publishing from
the environment `pypi`, with attestations. Dependabot updates
uv.lock, the Dockerfile's digests and the actions. Changes go in
`CHANGELOG.md`, under `## Unreleased`, which `tools/release.sh` turns into
the release's section and notes. The script releases only what CI has
passed, puts everything back if it fails before the push, and after a
failure past that point, running it again publishes the version that was
pushed. Published releases stay: a broken release gets a fixed release.
GitHub enforces it: releases are immutable, and rulesets keep main from
force-pushes and deletion, and version tags from moving or deletion.

Running the bot requires a reachable signal-cli-rest-api and a `config.toml`
(made from `config.example.toml`):

```sh
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DEBUG=1 uv run nejomibot
```

Debug mode talks only to `debug_group` and the admins, and keeps its files
in a private temporary folder, created anew at each start. Stop the
production bot first: two bots on one account compete for incoming
messages.

Profile in the image, which has its bytecode, rather than in a checkout run
with `PYTHONDONTWRITEBYTECODE`, which compiles every import anew. Python's
sampling profiler runs a script (`python -m profiling.sampling run --mode
cpu --collapsed -o out.txt script.py`) or attaches to a running bot
(`podman exec --user 0 NAME python -m profiling.sampling attach
--async-aware -d 30 --collapsed -o /data/out.txt 1`), which takes a
container started with `--cap-add SYS_PTRACE`. `--async-aware` follows
asyncio's tasks but not `asyncio.to_thread()`'s threads, which `--mode cpu
-a` does; prefer `--collapsed` to `--pstats`, which can't save the garbled
names that sampling other threads reads at times; and `--blocking` gets
whole stacks, but in `--mode wall` only.

## Architecture

Each module's docstring explains its feature as an admin uses it; read it
before changing the module. What follows is what spans modules, or isn't
obvious from the code.

**Startup** (`bot.main`): the settings (`config.py`, pydantic-settings: TOML
from `NEJOMIBOT_CONFIG` or `./config.toml`, overridden by `NEJOMIBOT_*`
variables; `extra="forbid"`, so a renamed or removed setting stops the bot
with a message). `wait_for_account()` polls signal-cli-rest-api until it has
the account, answering the container health check meanwhile
(`rest.accounts()` reads both of upstream's `/v1/accounts` formats). Then
`SignalBot`, the outbox (with the messages kept from the last run), the
allowed list, the handlers, the timers and the health checks; `bot.start()`
runs signalbot's event loop and APScheduler, and signalbot takes over
SIGTERM; `bot.shutdown()` cancels the bot's tasks, keeps the waiting
messages, and closes the HTTP session and the loop. Jobs that must not be
skipped when late have `misfire_grace_time=None`. The wait and signalbot run
two event loops, one after the other: nothing bound to a loop (the HTTP
session, locks, tasks) may pass from the first to the second, which is why
the wait closes its session.

**Who may use what** (`bot.handlers`, `access.py`): handlers with
`everyday = True` are registered for every chat, filtered by
`access.permits` for each message (admins and allowed contacts in direct
chats, groups on the allowed list); admin handlers for direct chats only,
filtered by `access.from_admin`. The admins are the configuration's
`admins` and those they add with `/admin add`, kept in
`data_dir/admins.txt` by Signal ID only, as a phone number can change hands;
only the configuration's admins add and remove admins
(`is_config_admin`), and get the notices, run the timers and are named in
the greeting. `/delete` is registered everywhere and checks for an admin
itself; in groups it takes nothing after it, as `/delete list` and
`/delete 2,5` show and delete what the bot sent to every chat; `/mention`
is registered for the admins in every chat too. The bot answers each person
at most `command_limit` commands in `command_limit_minutes`
(`commands.admitted()`), but not the admins, nor what runs under
`collected`. `/contacts` and `/trust` share one numbering, the order each
admin was shown last (`contacts.shown`), which `<who>` in `/allow` and
`/admin add` takes too.

**Commands and aliases** (`commands.py`): every handler is a
`commands.Handler` listing its `Command`s: the English name, whether more
may follow it, whether timers and `/run` may run it, and its subcommands.
Every name the bot answers to starts with `/`: a plain word in the aliases
or in an album's or special's shortcuts is taken with a `/`
(`config.as_command()`). An alias is replaced by its command once for each
message (`commands.resolved_message()`), from, each taking precedence over
those before: the albums' and specials' shortcuts (`Handler.shortcuts()`),
the bot's own (`commands.ALIASES`), every language's names
(`locale/<language>.toml`, accepted from anyone) and the configuration's
`aliases`; `canonical()` also replaces a language's subcommand words right
after the command, so handlers, timers and specials read English.
`answer()` does what every command does: the log, the read receipt and the
typing indicator beside the command, the reply, a failure as
`error_text()`, and what an edit does (see Conventions).
`commands.known()` finds any command, specials included, so the `timers`
flag alone decides what timers may run; `commands.built_in()` only those the
handlers list. A new command goes into its module, `bot.handlers()`,
`help.py` (its line and its page) and the README's tables, which the tests
check, and gets a name in each language's `.toml` unless the English one is
the language's word too.

Commands may start with `.` or `!` in place of `/`: `config.slashed()`
makes either a `/` wherever commands are read, so the code, the
translations and the bot's files keep `/`. The bot shows them with `command_prefix`: `_()` and
`ngettext()` pass messages through `i18n.prefixed()` before values go in,
and a name put into a message gets `prefixed()` where it goes in
(`help.shown_name()`). The tests run with `/`;
`test_the_prefix_shows_only_commands` keeps every `/` in the messages a
command's name or one of `EXAMPLES`, and each translation with as many.

**Help** (`help.py`): `/help` lists the everyday commands, a short line each
(`Entry.what`), in groups (`EVERYDAY`), and for an admin in a direct chat,
the admin commands by name (`ADMIN`). `/help <command>` (`help_for()`)
resolves the word as `canonical()` does and shows the command's line, then
its page (`Entry.page`, and `Entry.admins` for an admin in a direct chat). A
page is one message to translate, a line each, its `{fields}` filled by
`fields()`; a line that starts with a command and has a ` – ` (`DASH`) is an
example, shown in monospace, so translations keep the dash. The tests keep
`/help` and every page within the 2,000 bytes a bubble shows whole, in every
language, and each translation with as many examples as the English.

**Sending** (`messages.py`): handlers answer through `reply()` and `send()`
to the `Outbox`: each chat's messages go out in order; sends that surely
failed are retried for `send_retry_hours`, with a note that they're late; a
`SentLog` keeps what was sent, for `/delete` and `/delivery`. While Signal
rate-limits the bot (a 429), nothing is tried at once: new messages wait,
receipts and typing are skipped, and only the message that has waited
longest is tried (`Outbox.probe`), less and less often, up to
`rate_limit_retry_minutes`, or soon after an admin's command (`nudge()`). A
message that has waited 30 seconds, and every waiting message at shutdown,
gets a file in `data_dir/outbox`, loaded at the next start. Under the
`collected` ContextVar (timers, `/run`, specials) replies are gathered
rather than sent; under `to_terminal` (nejomibot-chat) they go back to the
terminal, and the command otherwise runs as in a direct chat. Neither came
in a Signal message, so neither gets a read receipt or typing
(`messages.from_signal()`). A `PerChat` message has a text of its own for some chats,
as `/today`'s birthdays. Long messages need nothing: signal-cli sends and
receives texts over 2,000 bytes as Signal's apps do.

Mentions are text inside the bot: `resolved_message()` writes a received
message's mentions into its text as `<@ID>` (`styles.written()`), which
handlers and files keep as they are, and `send()` makes each `<@ID>` a
mention again (`styles.mentioned()`). Their places count UTF-16 code units,
in a styled message after signal-cli-rest-api has read its marks.

**Timers** (`timers.py`) run each command through the real handlers as a
made-up direct message from the first admin (`made_up()`,
`Timekeeper.handle`, which nejomibot-chat shares; `Timekeeper.answers_to`;
`/run` and specials as whoever sent them, where they sent them), then post the
collected answers to the timer's chats, in each chat's language, all from
one `messages.Draw` so every chat gets the same photo. They can't run what
changes timers, specials, birthdays, albums or who may use the bot, what
posts elsewhere, what answers for its own chat, nor `/delete` and
`/contacts add` (`Command.timers`); a command that lists and changes, as
`/timers`, has a second `Command` with `timers=False`. A list shown under
`collected` doesn't change the numbers an admin's commands take (their
`shown`). `nejomibot-timers` (`timers_cli.py`) edits the same file.

**Specials** (`specials.py`) post their texts and what their commands
answer, as whoever ran them; their parts can't be other specials, nor
commands timers can't run. Making one for everyone names its admin
commands (`admin_commands()`), as everyone who uses it gets their answers.
Texts keep the formatting given in Signal: `styles.marked()` writes it as
signal-cli-rest-api's marks, checked by reading them back as its parser
does (`styles.unmarked()`).

**Photos** (`photos.py`, `albums.py`): the folders directly in `photos_dir`
are the albums. `/uniquephoto`'s rounds are independent:
`sent-photos.txt` for the library, `album-rounds.txt` for the albums.
Photos go out at full size. Paths are handled as text (`library_name()`,
`scan_photos()` through `iterdir()`), as pathlib's `relative_to()` and
joined paths cost tens of milliseconds a command for thousands of photos.
`moments()` is the one index of when photos were taken, read in the
background after the start (`index()`) and kept in
`data_dir/photo-index.txt` (`index_key()`): bump `INDEX_FORMAT` when what
`exif_datetime()` makes of a photo changes. An album's shortcuts are aliases
for `/photo <album>` (`Photo.shortcuts()`), left out of `check_aliases()`
so `albums.txt` can't stop the bot from starting.

**The day** (`today.py`, `holidays.py`, `birthdays.py`): the holidays come
from rules for 35 countries (`config.Country`, kept equal to
`holidays.COUNTRIES` by a test); only Sweden's and Greece's names are
translated, and the other countries reuse those names where a day means
the same. Birthdays and name days show in groups only.

**Notices** (`notices.py`): at every start, once the bot is ready, unless
`startup_notice` is false, the configuration's admins get one message
(`start_text`) of how the start went, what needs their attention and how
the bot is, reusing `/status`'s functions; `data_dir/run.json` keeps each
run's version, start and clean stop. They're also told when Signal starts
rate-limiting the bot (tried once), and of changed safety numbers.

**Beyond signalbot**: direct signal-cli-rest-api requests are in `rest.py`,
pydantic models for its answers in `account.py`. signalbot drops receipts,
so `delivery.py` hears them on a websocket of its own (`rest.received()`),
and drops signal-cli-rest-api's error text, so `messages.describe()` words
the HTTP status. Every request the bot makes itself shares one aiohttp
session (`client.py`). aiohttp's error text can contain the URL, with the
OpenWeatherMap key or a phone number: word such errors with `describe()` or
`web_error()`, never with `str(e)`.

**Health**: `health.py` checks signal-cli-rest-api, the bot, Signal's
servers and delivery (what `delivery.receipts` hears) every
`healthcheck_minutes`, and pings `healthcheck_url`; `/status` shows the
same through the same functions. The bot check tells of each send the
outbox gave up on, and each message it dropped, in one round only: a
round's `Health` keeps the outbox's counts, which the next round and
`/status` take from theirs (`Rounds.reported`). The container's check
(`healthcheck.py`) asks the bot over the abstract Unix socket
`\0nejomibot-health`, for liveness only: it fails when the bot doesn't
answer or its rounds are late, never because Signal or signal-cli-rest-api
fails (a restart wouldn't help, and could lose messages not yet on disk),
nor while the bot waits for the account.

**nejomibot-chat** (`chat_cli.py`, the client, which imports nothing else
of the bot's, like `healthcheck.py`; `terminal.py`, the bot's side) talks to
the running bot over the abstract Unix socket `\0nejomibot-chat`, which
opens once signalbot is ready, and which the bot answers only for its own
uid and root (`SO_PEERCRED`), as signal-cli-rest-api's container shares the
bot's network namespace in the Quadlet. A request is a JSON line, with the
attached files' bytes after it, and the client half-closes once it has
sent it, but for `--follow`, where the bot takes the end of its input as
the client leaving; after a refusal the bot reads what is still coming
(`drain()`), since closing a Unix socket with unread data resets it before
the client reads why. Each answer, and each received message, is a JSON
line, which `--json` prints as it is. A message runs through
`Timekeeper.handle` as from the first admin, its files as signalbot's
`Attachment.base64_content`, at most `MAX_ATTACHED` together, as they pass
through the bot's memory, and its marks as Signal's text styles
(`styles.typed()`, which styles only marks that open at a word's start
and close at a word's end, as WhatsApp does, unlike signal-cli-rest-api's
`unmarked()`, which drops a mark left open). `terminal.recent` is an `incoming.Inbox` for
every chat (`wanted()`, `files_of()`), the latest 100, with a queue for
each follower. A request with `chats`, numbers from /chats, is for those
chats: its text runs there as /run does, if it starts with a command
(`for_chats()`), or else posts there as /msg does, and recent and follow
give only their messages (`in_chats()`), after a header with the chats'
names and how many of the latest come. `--to` without a message, in a
terminal, is a chat with them (`connected()`): `Screen` shows what comes
above the line being typed, and draws that line again, told the prompt is
up by GNU readline's pre-input hook, as the image's Python has it (uv's
editline calls none); the bot ending the chat ends the line with SIGINT.

**nejomibot-account** (`account_cli.py`) asks signal-cli-rest-api itself,
one request at a time, through urllib, for what signalbot doesn't do:
registering, linking, the PIN, privacy, devices, safety numbers and rate
limits. It runs without the bot, before the configuration is complete, so it
reads only `signal_service`, `account` and `data_dir`, from their
`NEJOMIBOT_` variables or loosely from the config file (`tomllib`), and
imports `profile.py` only where it changes the profile: through
`profile.keep()` and `keep_avatar()` into `bot.txt`, with avatars made as
`/avatar` makes them (`make_avatar()`). As root, the files it replaces keep
their owner (`files.replace_privately`). segno draws the QR code for
linking, imported only there.

**The bot's profile** (`profile.py`): kept in `data_dir/bot.txt`, which
`/name`, `/about`, `/avatar`, `/username` and `nejomibot-account` write. At
each start `keep_profile` changes only what differs from the account's
profile, so a start that changes nothing sends nothing; name, About and
avatar go in one update, as one without the avatar removes it.

**Files the bot keeps** in `data_dir` are written through
`files.write_privately` (mode 0600, a temporary file, fsync, replace, fsync
of the folder) or `files.append_privately`. The line-based files keep hand
edits, comments and unreadable lines as they are; a new one uses
`files.KeptLines`. In debug mode they're in a temporary folder.

**Translations** (`i18n.py`): messages are written in English, marked with
`_()`, `ngettext()`, or `N_()` in tables, and formatted after translation:
`_("Weather in {city}").format(city=...)`. After changing messages, run
`tools/translations.sh` and translate every `.po` (Greek: serious, not
silly or chatty); `tests/test_i18n.py` fails on an untranslated, fuzzy or
obsolete message, or differing `{fields}`. The image and the wheel have
the `.po` files compiled to `.mo` files, which stay out of git. A new
language is its `.po` and `.toml` alone (`tools/translations.sh <code>`),
and no test names the languages. Each chat may have its own (`/language`): `language()` reads the
`speaking_now` ContextVar, which `Handler.handle_data_message` sets, so
handlers need nothing; what the bot sends on its own sets it for each chat.
A language's catalog loads only once the bot speaks it.

## Conventions

- Handlers never raise: `answer()` posts failures with
  `messages.error_text()` ("Something went wrong: …") and logs them with
  `messages.log_failure()`: an expected failure (a file or service failing)
  in a single line, a bug with its traceback.
- The log says what happened and where, not who was involved: INFO has
  command names and the kind of chat (`chat_kind`, `to_whom`), never phone
  numbers, Signal or group IDs, or message text; those go at DEBUG.
  `log_level` sets the bot's own level, and every library logs at WARNING
  through the same handler. signalbot's logger stays at WARNING: at INFO, it
  logs every message the bot receives, in full.
- Styled replies (`TextMode.STYLED`) need `messages.escape()` on any text
  from outside, such as names and errors; a special's texts are already in
  marks.
- An `EditMessage` is a `DataMessage`, and `answer(edits=...)` says what an
  edit does (`commands.Edits`): `RUN_AGAIN`, for commands that show
  something or set a value; `REPLACE`, for those that add or remove
  something, which say how to undo it with `undo_with()` (or
  `cannot_undo()`), so that an edit undoes what its message did, then runs;
  `NOT_RUN`, for posts and deletions, which says so; and `IGNORE`, for
  `/delete` alone. What a command did is kept by its message for a day, in
  memory, and also under an edit's own timestamp, because Signal Desktop
  names the latest edit while other clients name the first message; an edit
  of a message from before the start isn't run. A new command that changes
  something uses `REPLACE` and registers its undo; `KeptLines` changes
  provide one (`revert`).
- Python 3.15 only, the latest (rule 13), so the code may use anything it
  has, as it does `except A, B:` without parentheses (PEP 758) and `type`
  aliases.
- Tests: `tests/conftest.py` gives each test fresh settings, lists and debug
  folder, points `signal_service` at `127.0.0.1:1`, closes the HTTP session,
  and imports `nejomibot.bot` so that every handler is known; its `answers`
  fixture keeps what commands answer. `tests/helpers.py` has the made-up
  people and groups, `message_from`, `make_jpeg` and `FakeApi`, a stand-in
  signal-cli-rest-api (import from there, not from conftest); the `bot`
  fixture is a real signalbot running against it. Deprecation warnings fail
  the tests. All test data is made up.
- Comments and docstrings are short, plain sentences that say what something
  does and why; module docstrings explain the feature as an admin uses it.

## Resource budget

Measure memory and the images' size when adding a dependency or anything
heavy, against these figures (amd64 on a desktop, as of 0.99.27):

- Peak RSS after the imports, every language's names, the Swedish catalog
  and a 1024×768 picture: about 76 MB; Python's allocations after the same,
  without the picture (tracemalloc): 38.9 MB. The running bot: about 88 MB
  after a start, with Pillow and the photo index of 7,600 photos loaded
  (about 400 bytes a photo), and 88 to 90 MB after a round of commands. On
  a Raspberry Pi 4: 90 MB, beside signal-cli-rest-api's 360 MB in json-rpc
  mode.
- Images: amd64 228 MB, arm64 246 MB, arm/v7 208 MB, as the sums of `podman
  history` (`podman image inspect` also counts the ID-mapped copy of the
  top layer that an image run with `--userns keep-id` gets).
- Speed: most commands answer in 2 to 5 ms, photos in 17 to 32 ms, and
  `/photo <date>`, `/albums` and `/onthisday` in 55 to 60 ms once the index
  is built; `nejomibot-timers` starts in about 0.5 s (2.4 s on the Pi 4).
- PEP 810's global lazy imports (`PYTHON_LAZY_IMPORTS=all`) don't work: the
  handlers register their commands as they're imported.
