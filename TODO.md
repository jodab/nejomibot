# TODO

What's left of the review of all the code, tests, tools, image and deploy
examples on 2026-10-17 (nejomibot 0.92.0), worked through the same day:
[Open](#open) lists what still needs the owner, or someone upstream;
[Done](#done) what was changed, and how. The changes are in
[CHANGELOG.md](CHANGELOG.md) under 0.93.0.

The project's own checks all pass: ruff, ruff format, strict pyright, the
tests, ShellCheck, and actionlint on the workflows.

## Open

### Decisions for you

These would change what people in Signal see, or how the bot is run, so they
wait for the owner.

- [ ] **Built-in hidden aliases:** `/test` for `/status`, `/time` for
  `/info`, `/safety` for `/contacts`, and `/timer delete` for `remove`,
  beside the configurable aliases. Keep them, or move them to
  `locale/*.toml` or the config's aliases, so there is one mechanism.
  They're now the `hidden` names of each `Command`, in one place. (The plain
  words are gone: see Asked by the owner, 2026-10-18.)
- [ ] **`/dailyquote` is an admin command, as `/dailypost` is** (2026-10-18):
  for timers, `/run` and the admins in a direct chat, like every special.
  Unlike `/dailypost`, it uses nothing up, so it could be an everyday
  command, for everyone allowed; they have `/fortune` already.

### For you to do

- [ ] **Ask signalbot for what the bot can't do without it.** Filing issues
  is the owner's to do; drafts below. The first matters most: until signalbot
  marks sync messages, the bot can only warn against linking.
  1. *Mark sync messages.* `parse_source_from_envelope`
     (`signalbot/_utils/source.py`) puts a sync message's destination in a
     `DataMessage`'s source fields, so a bot can't tell what its own account
     sent from another device from what the other person sent. On an account
     linked to a phone, or with Signal Desktop, a command typed there in a
     direct chat looks like the other person's. Please keep the envelope's
     source for sync messages and mark them (say `DataMessage.is_sync`, with
     the destination apart), so a bot can ignore them, or handle them
     knowingly.
  2. *Keep signal-cli-rest-api's error text on `SendError`.* It's raised as
     `SendError(str(exc))` from aiohttp's `ClientResponseError`, which has
     only the status, so signal-cli-rest-api's `{"error": "..."}` is lost: a
     bot can't tell a permanent failure (an unregistered recipient, untrusted
     keys) from a temporary one, and retries both for hours. Please keep the
     status and the error text on the exception.
  3. *Close the storage.* `SQLiteStorage` opens a connection and has no
     `close()`; every `SignalBot` leaves one open (`ResourceWarning:
     unclosed database`). `SignalBot.stop()`/`close()` could close it.
  4. *Name recipients at DEBUG only.* `MessageActions._log_send_errors` logs
     "Message … not delivered to <number>" at WARNING; a bot that keeps
     phone numbers out of its log at WARNING can't, short of filtering
     signalbot's lines. The warning without the recipient, and the recipient
     at DEBUG, would do.
  5. *Depend on phonenumberslite.* signalbot only parses phone numbers and
     checks that they're valid (`_recipients.py`), which phonenumberslite
     does as well; phonenumbers adds 41 MB of place names, carriers and time
     zones, 15% of a bot's image. The bot swaps them with uv's
     `exclude-dependencies` meanwhile; with signalbot asking for the lite one,
     that could go.
- [ ] **`fortunes_svenska` has no stated source or license.**
  [README.md](README.md#license) covers fortune-mod's files only. It reads
  like a Swedish translation of fortune-mod's `fortunes`; record where it
  comes from, and its terms, before publishing.
- [ ] **Install the Ruff extension in VS Code** (`charliermarsh.ruff`): this
  folder's untracked settings now format Python with it, as the project
  does, and turn Pylint off here; neither Ruff's nor Black's extension was
  installed, so format on save did nothing.

### The day images go to ghcr.io

Everything is in place, and nothing is published until a release is:

1. Bump the version and date the CHANGELOG, and push to GitHub. CI
   runs the checks and builds the image, without pushing it. On a private
   repository that takes Actions minutes; on a public one it's free.
2. Publish a release on GitHub, tagged `v` and the version, such as
   `v0.93.0`. [Release](.github/workflows/release.yml) checks the tag
   against pyproject.toml, runs `tools/build-image.sh --source ... --push
   ghcr.io/OWNER/nejomibot`, and so pushes `:VERSION` and `:latest` for
   amd64 and arm64, labelled with the repository.
3. On GitHub, make the package public (packages start private).
4. Point the docs and examples at it: `Image=ghcr.io/OWNER/nejomibot:VERSION`
   in [deploy/](deploy) and a pull in the README's Running it, instead of
   `localhost/nejomibot`.
5. Maybe: build provenance (`actions/attest-build-provenance`) or a cosign
   signature, so users can check where an image came from.

### Upstream

- [ ] **signal-cli-rest-api is pinned to a CI build.** [deploy/](deploy) uses
  `1791633879-ci`, now by digest, as 0.101 is broken for the bot (#885, #892,
  signal-cli#2119); 0.101 was still the latest release on 2026-10-17. Move to
  the next release once it's out, then revisit `LAST_TOO_OLD` in
  [health.py](nejomibot/health.py).

## Done

### P1

- [x] **Linked-device mode lets the phone's owner act as anyone they chat
  with, admins included.** `signal-account.sh` warns, and asks, before it
  links (in `setup` and `link`, and in its help); the README says the bot
  needs a number of its own, registered, under Who may use what, Running it
  and the account tool. The real fix needs signalbot: see the drafts above.
- [x] **OpenWeatherMap's requests by city name are deprecated.** The bot asks
  OpenWeatherMap's geocoding where `weather_city` is, once, keeps the
  coordinates in memory, and asks for the weather by `lat` and `lon`. Same
  post, same settings; an unknown city now says so.
- [x] **The exchange-rate endpoint is legacy.** `/info` uses
  `open.er-api.com/v6/latest/{base}`, checks the HTTP status and `result`,
  and says what went wrong. No attribution, as the owner decided.

### P2

- [x] **Logs keep phone numbers and message text.** Commands are logged by
  name and kind of chat (`commands.answer`), sends by kind of chat; who, what
  follows the name and whom a message goes to only at DEBUG, with the new
  `log_level` setting. Unreadable lines of the data files are logged by
  number, not content; network errors through `describe()`. Left:
  signalbot's own warning that a group message didn't reach someone names
  them (ask 4 above).
- [x] **The OpenWeatherMap key can end up in a chat and in the log.** aiohttp
  errors are worded by status, or by kind (`messages.web_error`): besides
  `ClientResponseError`, `ConnectionTimeoutError`'s text has the URL too.
- [x] **The deploy examples don't harden the bot's container.**
  `DropCapability=ALL`, `NoNewPrivileges=true`, `ReadOnly=true` and
  `RunInit=true` in the Quadlet; the same in Compose, with a tmpfs on `/tmp`.
  `signal-account.sh` and `nejomibot-timers` work in it.
- [x] **`/contacts` can fire hundreds of requests at once.** Four at a time,
  at most fifty for each command.
- [x] **A rate-limited bot keeps trying every two minutes.** After a 429,
  waiting messages are tried every half hour, until a message goes out.
- [x] **Scheduled jobs are skipped when the event loop is a second late.**
  `misfire_grace_time=None` for the health rounds and the timers' reread.
- [x] **Contact lookups grow with the cube of the account's size.** `Account`
  indexes people, safety numbers and groups by ID once.
- [x] **Atomic writes aren't durable.** `files.write_privately` syncs the
  file before it replaces the old one, then the folder.
- [x] **The runtime image carries uv and a second copy of the code.** The
  venv is built in a stage of its own; 275 MB instead of 323 MB (amd64).
- [x] **A new aiohttp session for every request.** One, `client.py`, closed
  as the bot stops.
- [x] **Most handlers repeat the same steps.** `commands.answer()` does them.
- [x] **Unexpected errors are logged without a traceback.**
  `messages.log_failure()`: expected failures in a line, bugs with their
  traceback. (Ruff's TRY400 now lists only expected failures, logged in a
  line on purpose, so it isn't enabled.)
- [x] **Every command is listed in seven places.** Each handler declares its
  `Command`s, from which timers, `/run` and the alias checks work; tests catch
  a command missing from `bot.handlers()`, `/help` or the README.
- [x] **tools/timers.sh re-implements timers.py, and has drifted.** Replaced
  by `nejomibot-timers` (`timers_cli.py`), which reuses timers.py.
- [x] **No CI.** [CI](.github/workflows/ci.yml) and
  [Dependabot](.github/dependabot.yml) (uv, the Dockerfile's images, the
  actions); actions pinned by commit.
- [x] **The image's group is 999, not 1001.** `groupadd --gid 1001`, and
  `USER 1001:1001`.
- [x] **Dependencies are behind.** signalbot 2.1.0, Pillow 13.0.0,
  pydantic-settings 2.16.0, pydantic 2.14.1.

### P3

- [x] **Shutdown leaves the bot's own work behind.** `bot.shutdown()`
  cancels it, keeps the waiting messages, closes the session and the loop.
- [x] **A new timer can take the number of a line the bot couldn't read.**
- [x] **Two daily posts at the same moment can pick the same photo.** A lock.
- [x] **The sent-photos file is the odd one out.** UTF-8 and 0600.
- [x] **Debug mode uses fixed names in the shared temp folder.** A private
  folder per run; temp files through `mkstemp`.
- [x] **Log timestamps print an extra zero.** Python's usual format, with
  the date; signalbot's lines through the same handler; a `log_level`
  setting. Found on the way: APScheduler logged every job run at INFO, two
  lines every 30 seconds for the timers' reread alone; libraries now log
  warnings only.
- [x] **exifread does what Pillow already does.** Pillow reads EXIF with the
  header, one open per photo fewer; the captions are the same.
- [x] **All fortune libraries stay in memory once `/fortune` is used.** Only
  the counts are kept; a library is read when asked for, each fortune as
  likely as before.
- [x] **Unused and leftover code.** `aliases_of`, the `TRIGGERS` and
  `COMMANDS` tables, `timers.names_of` and the allowed list's watch on its
  path are gone; ruff's `extend-exclude`; `.gitignore` without setuptools'
  entries, with `dist/`. The personal entries are in this clone's
  `.git/info/exclude`.
- [x] **profile.py imports photos.py for a side effect.** `format_file_size`
  is in i18n.py; HEIF is registered by `photos.open_image`, when first used.
- [x] **What timers can't run is decided in three places.** `Command.timers`.
- [x] **`timers.card()` builds the date by hand.** `day_and_time()`.
- [x] **`/info` doesn't check the HTTP status.** With the endpoint move.
- [x] **No init process in the container.** `RunInit=true`, `init: true`;
  the SIGTERM handler stays for runs without one.
- [x] **Image pinning and labels.** Base images by digest, kept current by
  Dependabot; `build-image.sh --source` adds `org.opencontainers.image.source`
  and the commit.
- [x] **Tests import from conftest and from signalbot's internals.**
  `tests/helpers.py`, and signalbot's public names.
- [x] **111 ResourceWarnings in the test run.** Filtered; deprecation
  warnings fail the tests.
- [x] **Shared shell code is copied.** timers.sh is gone.
- [x] **Local editor settings use other tools.** See For you to do.
- [x] **No changelog.** [CHANGELOG.md](CHANGELOG.md).
- [x] **tidy-photos.sh's help is out of step.**

### Decided by the owner, 2026-10-17

- [x] `/avatar` stays as it is: whoever wants it enables attachments in
  signal-cli-rest-api.
- [x] `/msg` and `/run` say which chats only got it queued, or may not have
  (`Outbox.send` returns the outcome).
- [x] Error replies keep showing what went wrong, in every chat.
- [x] Captions keep Google Maps links; `photos_map = "openstreetmap"` gives
  OpenStreetMap's short links (`https://osm.org/go/...?m=`).
- [x] No attribution for the exchange rates, for now.
- [x] Timers and `/run` may still run `/delete`.
- [x] The example date doesn't age: the next Christmas Eve in `/help` and the
  `/timer` usage, a format in the README.
- [x] Swedish month names stay capitalized; `/info`'s currency emojis stay.
- [x] HEIF is a setting, `photos_heif`, on by default.
- [x] Photos are still sent at full size.
- [x] Waiting messages are kept in `data_dir/outbox`: a message waiting half
  a minute gets a file of its own, every waiting one at shutdown, so brief
  outages write nothing.

### Asked by the owner, 2026-10-18

- [x] Translations are compiled as the image is built, not at every start:
  the Dockerfile's `translations` stage makes a `.mo` of each `.po` with
  polib, from the lock, and the image gets the `.mo` files alone, which the
  bot reads with Python's gettext. No apt, no gettext tools: a 21 kB wheel.
  From a checkout, without `.mo` files, the bot reads the `.po` with polib,
  now a development dependency only. Measured in the image: Swedish loads in
  2 ms instead of 9, without polib's import; memory is the same, within a MB.
- [x] Specials (`specials.py`): `/dailypost`, moved from photos.py, the new
  `/dailyquote`, and the admins' own, made with `/special add` and kept in
  `data_dir/specials.txt`. They run their commands through the timers'
  `answers_to`, in order.
- [x] The bot's own names for commands all start with `/`: the plain words
  `info`, `weather`, `väder` and `vader` are gone, and tests keep it so. The
  config's aliases may still be plain words.
- [x] Version 0.93.0, and its CHANGELOG section dated, before the deploy.
- [x] A smaller image: phonenumberslite in place of phonenumbers (see the
  signalbot ask 5 above). The fortunes, 2.8 MB, stay as they are:
  compressed, they'd save 2 MB on disk and nothing in a registry, which
  compresses the layers anyway.
- [x] The containers' health checks run every minute, not every 20 seconds
  (the owner's change): about 2,900 runs a day for both containers instead
  of 8,600, each also a journal event, for recovery in about three minutes
  instead of a minute and a half. `healthcheck_events = false` in the
  host's containers.conf would drop the journal events too.

## Checked and fine

- No time bombs in the tests: they use fixed clocks, and the one date in 2030
  isn't compared with today; the example date is computed.
- signal-cli-rest-api isn't published in the examples; admin commands rely on
  signalbot's contact filter, which checks both number and Signal ID;
  `/delete` checks for an admin itself in groups; the allowed list is checked
  for every message.
- The container check can't restart-loop the bot while signal-cli-rest-api is
  down or misconfigured: the interval rounds record a result even before
  signalbot is ready.
- The image runs read-only, without capabilities, with an init process: it
  stops in a fraction of a second, and the tools work.
- Memory, measured 2026-10-17: about 74 MB RSS after imports and one picture
  opened, 71 MB with `photos_heif = false`; mostly signalbot, aiohttp and
  pydantic.
- signalbot 2.1.0 has nothing that would replace a function in rest.py, nor
  mark sync messages.
