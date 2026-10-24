# TODO

This file tracks what remains from the review of all the code, tests,
tools, image and deployment examples carried out on 2026-10-17 (nejomibot
0.92.0) and worked through the same day. [Open](#open) lists what still
needs the owner or someone upstream, along with plans that are waiting on
them, such as accounts without a phone number; [Done](#done) records what
was changed, and how. The changes themselves are described in
[CHANGELOG.md](CHANGELOG.md), under 0.93.0 and later.

All of the project's own checks pass: ruff, ruff format, strict pyright,
the tests, ShellCheck, and actionlint on the workflows.

## Open

### Decisions for you

These would change what people see in Signal, or how the bot is run, so
they wait for the owner.

- [ ] **When to move to 1.0** (2026-10-19): until you decide, nejomibot
  stays on 0.99.x, with patch releases only. `tools/release.sh` stops on
  minor and major releases; remove its guard (after the usage check) when
  the time comes.
- [ ] **A typed `|` in `/special add`** (2026-10-18): it is refused ("the
  file of specials uses it"), although only the first `|` on a line counts,
  and the file now contains the spoiler mark `||` anyway. The refusal could
  go, with a typed `|` stored as `\|`. Since 2026-10-24, a `+` standing on
  its own, not a `|`, joins a special's parts into one message, as a `|`
  would clash with the file's separator and the spoiler marks.
- [ ] **Choices made for the features of 2026-10-19** where you didn't
  specify, any of which can change:
  - The Swedish names: `/dennadag` (`/onthisday`), `/prognos`, `/påminn`,
    `/lista`, `/födelsedag`, `/födelsedagar`, `/namnsdag`, `/namnsdagar`.
  - Reminders are posted once (a weekly reminder is an admin's timer), with
    at most 20 per chat and at most a year ahead, and are dropped when more
    than a day late.
  - `/forecast` shows today and tomorrow, not more days.
  - The calendar leaves out days whose dates are set anew each time, such as
    the European Parliament election, and commercial days, such as
    Kanelbullens dag. Greece's 26 December is shown as Boxing Day, so that
    it shares a line with Sweden's.
  - The admins are notified of safety numbers that have changed and aren't
    trusted, not of new people.
- [ ] **Choices made for admins, numbering, backups and holidays**
  (2026-10-19, later) where you didn't specify:
  - `/admins` lists every admin: those in the configuration first,
    unnumbered, then the added ones, numbered for `/admin remove`. Only the
    configuration's admins (all of them, not just the first) can add and
    remove admins; added admins can do everything else. The notices, the
    timers' commands and the greeting remain with the configuration's
    admins. Added admins are stored by Signal ID only (your decision), so
    someone the bot doesn't know yet can't be added by phone number.
  - `/contacts` and `/trust` share one numbering; `/trust` lists everyone,
    including people without a safety number, so that the numbers match.
    Numbers work in `/allow` and `/admin add`, but not in `/birthday add`,
    where numbers refer to chats.
  - Backups: Zstandard rather than xz, which needs about 94 MB of memory to
    compress at its default level; at 04:00 unless `backups_at` says
    otherwise; no backup when the files' contents match the latest one, so
    a bot with a daily photo post, whose list of sent photos changes, still
    backs up daily; 30 kept, counted by number rather than age, so that a
    long stop doesn't leave only the one made after it; named like
    `nejomibot-2026-10-19_0400.tar.zst`, your name with the bot's in front,
    so a copy stored elsewhere says what it is; every file in `data_dir`
    except `run.json`, the outbox and files over 10 MB. A failed backup
    fails `/status`'s check, not the health check ping.
  - Holidays: the 27 EU member states, Norway, Iceland, Switzerland, the
    United Kingdom, the United States, Canada, Australia and New Zealand
    (for "the EU's top 10" by population, all 27 are included). The United
    Kingdom's are the bank holidays of England and Wales, Canada's the
    federal ones, and Switzerland's those that most cantons observe.
    Mother's Day and Father's Day are left out for Luxembourg and Bulgaria,
    whose dates aren't settled enough to be certain of. 26 December is
    shown as Boxing Day everywhere, St Stephen's Day included, as Greece's
    is.

### For you to do

- [ ] **Holidays in `/today`** (2026-10-19): set `holidays = ["SE", "GR"]`
  in the server's config.toml, since there are none by default, then add
  the birthdays and name days with `/birthday add` and `/nameday add`.
- [ ] **When the server gets the release after 0.99.13** (2026-10-23):
  while the bot is stopped for the update, remove the aliases for `/photo`
  from config.toml; right after it, add `/weather` after `/today` in the
  daily post's special, and give the album its shortcuts with `/album
  <album> shortcuts ...`. The daily post's special already has `/weather`
  (as of 2026-10-24).
- [ ] **When the server gets the release after 0.99.15** (2026-10-24): to
  have the day and the weather in one message, change the daily post's
  special to `/special add /dailypost /today + /weather; Dagens bild!
  /uniquephoto`, with the heading in bold as before.
- [ ] **Perhaps note on 0.94.0's release page that its images are broken**
  (2026-10-18), and that 0.94.1 should be used instead:
  `gh release edit v0.94.0 --notes-file ...`. The release stays published,
  as releases do.
- [ ] **Ask signalbot for what the bot can't do without it.** Filing the
  issues is the owner's task; drafts follow. The first matters most: until
  signalbot marks sync messages, the bot can only warn against linking.
  1. *Mark sync messages.* `parse_source_from_envelope`
     (`signalbot/_utils/source.py`) puts a sync message's destination in a
     `DataMessage`'s source fields, so a bot can't tell what its own account
     sent from another device apart from what the other person sent. On an
     account linked to a phone, or used with Signal Desktop, a command typed
     there in a direct chat looks as if the other person had sent it. Please
     keep the envelope's source for sync messages and mark them (for
     example, `DataMessage.is_sync`, with the destination kept separately),
     so that a bot can ignore them, or handle them knowingly.
  2. *Keep signal-cli-rest-api's error text on `SendError`.* It is raised as
     `SendError(str(exc))` from aiohttp's `ClientResponseError`, which holds
     only the status, so signal-cli-rest-api's `{"error": "..."}` is lost: a
     bot can't tell a permanent failure (an unregistered recipient, or
     untrusted keys) from a temporary one, and retries both for hours.
     Please keep the status and the error text on the exception.
  3. *Close the storage.* `SQLiteStorage` opens a connection and has no
     `close()`, so every `SignalBot` leaves one open
     (`ResourceWarning: unclosed database`). `SignalBot.stop()` or
     `close()` could close it.
  4. *Name recipients at DEBUG level only.* `MessageActions._log_send_errors`
     logs "Message … not delivered to <number>" at WARNING level, so a bot
     that keeps phone numbers out of its log at WARNING level can't do so,
     short of filtering signalbot's lines. The warning without the
     recipient, and the recipient at DEBUG level, would be enough.
  5. *Depend on phonenumberslite.* signalbot only parses phone numbers and
     checks that they are valid (`_recipients.py`), which phonenumberslite
     does as well; phonenumbers adds 41 MB of place names, carriers and time
     zones, 15% of a bot's image. Meanwhile, the bot swaps the two with
     uv's `exclude-dependencies`; if signalbot asked for the lite package,
     that could go.
- [ ] **Ask signal-cli-rest-api for signal-cli's version** (2026-10-18), for
  `/status` and the health check pings, which can't show it. Draft:
  *Report signal-cli's version in /v1/about.* `/v1/about` gives the REST
  API's own version (`BUILD_VERSION`, `unset` in CI builds) and the mode,
  but not the version of the signal-cli it runs, so a client can't tell
  which signal-cli it is talking to. The image knows the version at build
  time (`SIGNAL_CLI_VERSION`), and in json-rpc mode, signal-cli answers a
  `version` request. A field such as `signal_cli_version` would do.
  signalbot's `About` would need the field too (it drops unknown fields);
  in the meantime, `rest.py` could read it. Going around
  signal-cli-rest-api to signal-cli's own port (127.0.0.1:6001 in its
  container, which the bot can reach only because the examples share its
  network) isn't an API, so the bot doesn't do that.

### Accounts without a phone number

A plan, written on 2026-10-18; none of it has been done yet. The bot should
run on an account without a phone number, such as one created with Signal
Login, and work with people who have no phone number.

**Where things stand** (2026-10-18):

- *Signal:* Signal Login, in Signal Android's beta since 8.28 (September
  2026), creates an account without a phone number for a one-time fee of $3
  through Google Play. Signal Android shows its Account Key, which is the
  account's ACI, a UUID such as `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, and
  a Recovery Key: nothing else can restore the account. Existing accounts
  can't drop their number, and without a username, nobody can find the
  account.
- *signal-cli:* accepts an ACI wherever it accepts the account (`-a`, or
  JSON-RPC's `account`) since 0.14.6. Since 0.14.9, it can link to an
  account without a number (signal-cli#2123), and restore one as its primary
  device: `register --recovery-key KEY -a ACI`, with `--totp` when Signal
  asks for it. It can't create such an account, because the payment happens
  in the app store (signal-cli#2124, open). `listAccounts` returns
  `{"number": null, "aci": "..."}` (in text mode, `ACI: ...`), and what it
  receives carries the ACI as its `account`.
- *signal-cli-rest-api:* not yet supported; issue #889 is open, and a
  contributor there has a branch, for a pull request once signal-cli 0.14.9
  is in. Its paths accept an ACI where they take `{number}`, and pass it to
  signal-cli, and its websocket selects messages by that `account`, so
  sending and receiving work: they linked such an account and sent messages
  from it. Missing: `/v1/accounts` lists only numbers, so such an account
  shows up as `""`; the QR code for linking is fixed at version 10, which is
  too small for the longer link; and `register` can't accept a recovery
  key.
- *signalbot:* `Config.phone_number` can be any string, used in the paths
  and as the sender, so an ACI should work. This remains to be tried.

**Steps:**

1. Wait for signal-cli-rest-api's support, in a release or a CI build with
   signal-cli 0.14.9 or later, and pin it as now. Ask on #889 for what else
   the bot needs: `/v1/accounts` listing the ACI of an account without a
   number, and `register` with `recovery_key` (and `totp`).
2. For you to decide: an account to try it with ($3, and an Android phone
   with Google Play and the beta), and how the bot takes it over. Restored
   with its Recovery Key, signal-cli becomes its primary device, the phone
   gives it up, and the bot is the account's only device: this is the way to
   go. If linked instead, the phone keeps the account, and what is typed
   there in a direct chat reaches the bot as if the other person had sent
   it, just as with a number (see Who may use what in the README).
3. Make the code changes below, with tests.
4. Try it with the account on a signal-cli-rest-api of its own, posting
   only to the test group, then update the documentation.

**Code changes:**

- `config.py`: `account` already accepts a Signal ID. Also accept the
  Account Key as 32 hexadecimal digits without dashes, which signal-cli
  accepts too (check how Signal Android displays it), and convert it to
  signal-cli's form, lowercase with dashes: the form its messages carry,
  which signal-cli-rest-api compares as text. Update the comment on
  `account`, which says that a Signal ID may be used once
  signal-cli-rest-api supports accounts without a number.
- `bot.py`, `wait_for_account()`: `rest.accounts()` must find the ACI, in
  the form in which #889 lists it. Its message already says "account".
- `rest.py`: `accounts()` for the new list; every `account_path()` request
  tried with an ACI: devices, contacts, identities, trust, profiles,
  username and avatars.
- `profile.py`, `fetch_me()`: the fallback `Contact(number=account)` treats
  an ACI as a number; use `uuid=` for one.
- `/profile` and `/status`: show the ACI and the username where they show
  the number, and warn when an account without a number has no username,
  since nobody can find it then.
- `account.py`, `allowed.py`: `Account.id`, `is_me()`, and the check that
  the bot can't allow itself, with an ACI in place of a number.
- `tools/signal-account.sh`: `use_account()` rejects anything but a number:
  accept an ACI. `setup` and `register` should offer restoring with the
  Account Key and the Recovery Key, which are asked for the way PINs are and
  kept out of the shell history, and say that the phone will give the
  account up. `link` for an account without a number, once the QR code
  fits. `status` and `identities` should show the ACI; `privacy` and
  `search` are about numbers, so they should say so; `rate-limit --to`
  should accept an ACI or `u:username`; and `unregister` should warn that an
  account without a number can only be restored with its Recovery Key. Find
  out what `pin`, the registration lock, means without a number.
- People without a number: admins and the allowed list already accept
  Signal IDs, and `admins` gets them from `signal-account.sh identities`.
  `/contacts add` accepts only a phone number for someone the bot doesn't
  know yet; it could accept a username too, `u:name.42`, as signal-cli
  does. That changes a command, so it is yours to decide.
- Tests: made-up ACIs; the configuration accepts both forms and yields the
  dashed one; the wait finds an account by its ACI; `fetch_me()`;
  `/status`'s lines; and `FakeApi` answering for an account without a
  number.
- Documentation: the README (Who may use what, Getting started,
  Configuration, Setting up and managing the Signal account), DOCKERHUB.md
  and config.example.toml: the bot needs an account of its own, either a
  number registered for it or a Signal Login account restored into
  signal-cli, and without a number, a username.

### Upstream

- [ ] **signal-cli-rest-api is pinned to a CI build.** [deploy/](deploy)
  uses `1792271041-ci` (2026-10-17, upstream's 4b0f6f35; before that,
  `1791633879-ci`), by digest, because 0.101 is broken for the bot (#885,
  #892, signal-cli#2119); 0.101 was still the latest release on 2026-10-21.
  Move to the next release once it is out, then revisit `LAST_TOO_OLD` in
  [health.py](nejomibot/health.py).
- [ ] **signal-cli-rest-api support for accounts without a number** (#889,
  open): see Accounts without a phone number, above.
- [ ] **signalbot drops receipts** (2.1.3, 2026-10-21): its parser knows no
  receipt message (`UnknownMessageFormatError`, skipped), so
  [delivery.py](nejomibot/delivery.py) receives them on a websocket of its
  own, `rest.received()`. Once signalbot has a receipt message type and a
  handler for it, use those, and remove the second websocket.
- [ ] **signal-cli-rest-api drops what a websocket can't take at once:** in
  0.101 and builds from before 2026-10-13, each websocket gets an unbuffered
  channel, and a message is dropped while the previous one is still being
  written (`default:` in `JsonRpc2Client.ReceiveData`). Of a burst of
  receipts, some can be lost, so `/delivery`'s counts can come out too low,
  and in rare cases, a message meant for signalbot can be lost too. This was
  fixed on 2026-10-13 by 68ca0107 (a channel of 64), which the pinned
  `1792271041-ci` includes. Once a release includes it too, remove the note
  in delivery.py's docstring and in the README.

## Done

### P1

- [x] **Linked-device mode lets the phone's owner act as anyone they chat
  with, admins included.** `signal-account.sh` warns, and asks for
  confirmation, before it links (in `setup` and `link`, and in its help);
  the README says that the bot needs a number of its own, registered for it,
  under Who may use what, Running it, and the account tool's section. The
  real fix needs signalbot: see the drafts above.
- [x] **OpenWeatherMap's requests by city name are deprecated.** The bot
  asks OpenWeatherMap's geocoding once where `weather_city` is, keeps the
  coordinates in memory, and requests the weather by `lat` and `lon`. The
  post and the settings are the same; an unknown city now says so.
- [x] **The exchange rate endpoint is a legacy one.** `/info` uses
  `open.er-api.com/v6/latest/{base}`, checks the HTTP status and `result`,
  and says what went wrong. No attribution, as the owner decided.

### P2

- [x] **The logs contain phone numbers and message text.** Commands are
  logged by name and kind of chat (`commands.answer`), and sends by kind of
  chat; who sent a command, what followed its name and whom a message goes
  to are logged only at DEBUG level, with the new `log_level` setting.
  Unreadable lines in the data files are logged by line number, not by
  content, and network errors through `describe()`. Remaining: signalbot's
  own warning that a group message didn't reach someone names them (ask 4
  above).
- [x] **The OpenWeatherMap key can end up in a chat and in the log.**
  aiohttp errors are worded by status, or by kind (`messages.web_error`):
  besides `ClientResponseError`, the text of `ConnectionTimeoutError`
  contains the URL too.
- [x] **The deployment examples don't harden the bot's container.**
  `DropCapability=ALL`, `NoNewPrivileges=true`, `ReadOnly=true` and
  `RunInit=true` in the Quadlet, and the same in Compose, with a tmpfs on
  `/tmp`. `signal-account.sh` and `nejomibot-timers` work in it.
- [x] **`/contacts` can fire off hundreds of requests at once.** Now four at
  a time, and at most fifty per command.
- [x] **A rate-limited bot keeps retrying every two minutes.** After a 429,
  waiting messages are retried every half hour, until a message goes
  through.
- [x] **Scheduled jobs are skipped when the event loop is a second late.**
  `misfire_grace_time=None` for the health check rounds and the timers'
  reread.
- [x] **Contact lookups grow with the cube of the account's size.**
  `Account` indexes people, safety numbers and groups by ID once.
- [x] **Atomic writes aren't durable.** `files.write_privately` syncs the
  file before it replaces the old one, then syncs the folder.
- [x] **The runtime image carries uv and a second copy of the code.** The
  virtual environment is built in a stage of its own: 275 MB instead of
  323 MB (amd64).
- [x] **A new aiohttp session for every request.** Now a single one,
  `client.py`, closed when the bot stops.
- [x] **Most handlers repeat the same steps.** `commands.answer()` does
  them.
- [x] **Unexpected errors are logged without a traceback.**
  `messages.log_failure()` logs expected failures in a single line, and
  bugs with their traceback. (Ruff's TRY400 now flags only expected
  failures, which are logged in a single line on purpose, so it isn't
  enabled.)
- [x] **Every command is listed in seven places.** Each handler declares its
  `Command`s, from which timers, `/run` and the alias checks work; tests
  catch a command missing from `bot.handlers()`, `/help` or the README.
- [x] **tools/timers.sh reimplements timers.py, and has drifted from it.**
  Replaced by `nejomibot-timers` (`timers_cli.py`), which reuses timers.py.
- [x] **No CI.** [CI](.github/workflows/ci.yml) and
  [Dependabot](.github/dependabot.yml) (for uv, the Dockerfile's images and
  the actions), with actions pinned by commit.
- [x] **The image's group is 999, not 1001.** `groupadd --gid 1001` and
  `USER 1001:1001`.
- [x] **Dependencies are out of date.** signalbot 2.1.0, Pillow 13.0.0,
  pydantic-settings 2.16.0 and pydantic 2.14.1.

### P3

- [x] **Shutdown leaves the bot's own background work running.**
  `bot.shutdown()` cancels it, keeps the waiting messages, and closes the
  session and the event loop.
- [x] **A new timer can take the number of a line the bot couldn't read.**
- [x] **Two daily posts at the same moment can pick the same photo.** Fixed
  with a lock.
- [x] **The sent-photos file is the odd one out.** It is now UTF-8, with
  mode 0600.
- [x] **Debug mode uses fixed names in the shared temporary folder.** Now a
  private folder per run, with temporary files created through `mkstemp`.
- [x] **Log timestamps show an extra zero.** Python's usual format, with
  the date; signalbot's lines go through the same handler; and there is a
  `log_level` setting. Found along the way: APScheduler logged every job run
  at INFO level, two lines every 30 seconds for the timers' reread alone;
  libraries now log warnings only.
- [x] **exifread does what Pillow already does.** Pillow reads the EXIF
  data with the header, which saves one file open per photo; the captions
  are the same.
- [x] **All fortune libraries stay in memory once `/fortune` has been
  used.** Only the counts are kept; a library is read when it is needed,
  and each fortune is as likely to be picked as before.
- [x] **Unused and leftover code.** `aliases_of`, the `TRIGGERS` and
  `COMMANDS` tables, `timers.names_of` and the allowed list's watch on its
  path are gone, as is ruff's `extend-exclude`; `.gitignore` no longer has
  setuptools' entries, and has `dist/`. The personal entries are in this
  clone's `.git/info/exclude`.
- [x] **profile.py imports photos.py for a side effect.** `format_file_size`
  is in i18n.py, and HEIF support is registered by `photos.open_image` when
  first used.
- [x] **What timers can't run is decided in three places.** Now in one:
  `Command.timers`.
- [x] **`timers.card()` builds the date by hand.** It uses `day_and_time()`.
- [x] **`/info` doesn't check the HTTP status.** Fixed with the endpoint
  move.
- [x] **No init process in the container.** `RunInit=true` and
  `init: true`; the SIGTERM handler remains for runs without one.
- [x] **Image pinning and labels.** The base images are pinned by digest
  and kept current by Dependabot, and `build-image.sh --source` adds
  `org.opencontainers.image.source` and the commit.
- [x] **The tests import from conftest and from signalbot's internals.**
  They now use `tests/helpers.py` and signalbot's public names.
- [x] **111 ResourceWarnings in the test run.** Filtered; deprecation
  warnings now fail the tests.
- [x] **Shared shell code is duplicated.** timers.sh is gone.
- [x] **Local editor settings use other tools.** See For you to do.
- [x] **No changelog.** [CHANGELOG.md](CHANGELOG.md).
- [x] **tidy-photos.sh's help is out of date.**

### Decided by the owner, 2026-10-17

- [x] `/avatar` stays as it is: anyone who wants it can enable attachments
  in signal-cli-rest-api.
- [x] `/msg` and `/run` say which chats only got the message queued, or may
  not have received it (`Outbox.send` returns the outcome).
- [x] Error replies keep showing what went wrong, in every chat.
- [x] Captions keep their Google Maps links; `photos_map = "openstreetmap"`
  gives OpenStreetMap's short links (`https://osm.org/go/...?m=`).
- [x] No attribution for the exchange rates, for now.
- [x] Timers and `/run` may still run `/delete`.
- [x] The example date doesn't age: the next Christmas Eve in `/help` and in
  the `/timer` usage text, and a format in the README.
- [x] Swedish month names stay capitalized, and `/info`'s currency emojis
  stay.
- [x] HEIF support is a setting, `photos_heif`, on by default.
- [x] Photos are still sent at full size.
- [x] Waiting messages are kept in `data_dir/outbox`: a message waiting for
  half a minute gets a file of its own, and every waiting message gets one
  at shutdown, so brief outages write nothing to disk.

### Requested by the owner, 2026-10-18

- [x] Translations are compiled when the image is built, not at every start:
  the Dockerfile's `translations` stage makes a `.mo` file from each `.po`
  file with polib, installed from the lock file, and the image gets the
  `.mo` files alone, which the bot reads with Python's gettext. No apt and
  no gettext tools are needed, just a 21 kB wheel. From a source checkout,
  without `.mo` files, the bot reads the `.po` files with polib, which is
  now a development dependency only. Measured in the image: Swedish loads in
  2 ms instead of 9, without polib's import; memory use is the same, within
  a megabyte.
- [x] Specials (`specials.py`): `/dailypost`, moved from photos.py, the new
  `/dailyquote`, and the admins' own, created with `/special add` and stored
  in `data_dir/specials.txt`. They run their commands through the timers'
  `answers_to`, in order.
- [x] The bot's own command names all start with `/`: the plain words
  `info`, `weather`, `väder` and `vader` are gone, and the tests keep it
  that way. Aliases in the configuration can still be plain words.
- [x] Version 0.93.0, with its CHANGELOG section dated, before the
  deployment.
- [x] A smaller image: phonenumberslite in place of phonenumbers (see
  signalbot ask 5 above). The fortunes, 2.8 MB, stay as they are:
  compressed, they would save 2 MB on disk and nothing in a registry, which
  compresses the layers anyway.
- [x] The containers' health checks run every minute, not every 20 seconds
  (the owner's change): about 2,900 runs a day for both containers instead
  of 8,600, each also a journal event, in exchange for recovery in about
  three minutes instead of a minute and a half. `healthcheck_events = false`
  in the host's containers.conf would drop the journal events too.
- [x] The health check pings say what is running, as `/status` does: the
  versions, the uptime and the memory use. signal-cli's version isn't
  available: see For you to do.
- [x] A step-by-step setup guide: the README's Getting started, and
  [DOCKERHUB.md](DOCKERHUB.md) for Docker Hub. It was tested with the
  published images, up to the registration, including two likely mistakes.
- [x] The Docker Hub page is updated by each release: DOCKERHUB.md as of
  the release, and the repository's description, through
  `peter-evans/dockerhub-description`, once the images have been pushed,
  with a token that is allowed to delete (see below). First done by
  0.94.0's release.
- [x] Signed build provenance for every image a release pushes, keyless:
  `build-image.sh --digests` records what was pushed, by digest, and
  `actions/attest-build-provenance` attests it, for
  `gh attestation verify oci://IMAGE --repo jodab/nejomibot`. The digests
  were tested against a registry of our own. First done by 0.94.0's
  release: `gh attestation verify` accepts both registries' images, each
  by its own digest, as built by release.yml at the tag, from its commit.
- [x] A configuration file the bot can't read, or a `data_dir` it can't
  write to, stops it with a message that says so, and as which user it
  runs. Previously, it said the file didn't exist and carried on without
  it.
- [x] `fortunes_svenska`'s source and terms: recorded in the README's
  License section since the public release. It is the bot's own, proverbs
  and quotes from writers long dead in its own translations, so it comes
  under the bot's license.
- [x] The Ruff extension is installed in VS Code (`charliermarsh.ruff`,
  2026-10-18), so this folder's settings format Python with it on save.
- [x] 0.94.0's images were all amd64, labeled for the three platforms,
  each with arm/v7's variant: ubuntu-24.04's Podman 4.9 mixes up platforms
  when a build stage names its own platform, as the uv stage does
  (`--platform=$BUILDPLATFORM`; podman#22730, buildah#4742). This was
  reproduced with a small Containerfile: Podman 4.9.3 builds every platform
  as x86_64, while 5.7.0, on ubuntu-26.04, and 6.1.4 build each one
  correctly. The image jobs now run on `ubuntu-26.04`, the release installs
  `qemu-user-binfmt` there (what `qemu-user-static` has become, with the F
  flag) and checks it, and `build-image.sh` stops before pushing unless each
  image runs as its platform, which catches both the 4.9.3 build and the
  labels. 0.94.1, released with this the same day, came out right: on both
  registries, each platform's image is its own (the arm/v7 build kept the
  release under ten minutes), pulls for amd64, arm64 and arm/v7 find their
  own image, `latest` is the same manifest list as `0.94.1`, and both
  verify as attested.
- [x] A Docker Hub token that is allowed to read, write and delete, as
  `DOCKERHUB_TOKEN`: the 0.94.0 release's page job published DOCKERHUB.md
  and the repository's description on Docker Hub with it.
- [x] Text styles in the posts (2026-10-18). "Photo of the day!" and
  "Proverb or quote of the day:" are in bold: the caption and the quote are
  styled, with everything but the heading escaped, so a `~` in an
  OpenStreetMap link or a file name shows as it is. Your own specials keep
  the formatting the admin gives their text in Signal, which signalbot
  provides as `DataMessage.text_styles`: `styles.marked()` writes it as
  signal-cli-rest-api's marks, which `specials.txt` stores, and reads them
  back the way its `textstyleparser.go` does (`unmarked()`, tested against
  its own tests), so a combination the marks can't express is rejected
  rather than garbled. Stars are read up to three at a time there, so
  `*a **b***` closes neither style; spaces between bold and italic text take
  neither style, which keeps their stars apart and leaves only the cases
  where they meet inside a word. `***` requires signal-cli-rest-api 0.101 or
  later, which the bot requires anyway. Aliases move the styles along with
  the text (`commands.resolved()`).

### Requested by the owner, 2026-10-19

- [x] The names that commands have always had, `/test`, `/time` and
  `/safety`, are aliases, in `commands.ALIASES`, together with the
  language's and the configuration's, in a single mechanism; `/help` shows
  them, and the configuration's, on each command's first line. `/timer
  delete` remains a word that `/timer` accepts, while `/help` shows
  `remove`.
- [x] More text styles in the posts: "Weather in {city}" in bold, in
  `/weather` and the daily post; the explanation of a proverb in
  `fortunes_svenska` in italics, in `/fortune` and `/dailyquote`, with its
  source as before. Italics, the convention for a gloss, rather than a
  spoiler, which would hide it behind a tap. All 1,000 entries in
  `fortunes_svenska` were checked: the 299 explanations come out in
  italics, through `styles.marked()`, and every fortune in every library
  reads back unchanged.
- [x] `/delete list` and `/delete <n>`: the bot's latest messages, wherever
  it sent them, and deleting one by its number; since 0.97.1, the 50
  latest, and several at once, `/delete 2,5,11`, one after the other,
  stopping at the first one that fails, as the rest would likely fail too.
  The numbers refer to the list each admin was shown last, since anything
  the bot sends, the list included, would shift numbers counted from the
  newest. In memory only, as before (the owner's choice), and in direct
  chats only, as the list shows what was sent to every chat.
- [x] `/incoming` (`/inkorg`): the latest messages, 50 since 0.97.1, that
  anyone other than the admins sent the bot in a direct chat, commands
  included (the owner's choice), and `/incoming 4,9` forwards those
  messages in full to the admin who asks. Text only, since attachments stay
  ignored. In memory only; a sender's deletion for everyone and
  disappearing messages are honored, and edits replace the original.
  Timers and `/run` can't run it, since they would post what people wrote
  to others. Tested with signal-cli-rest-api's own envelopes, through
  signalbot's parsing and dispatch: a message, an edit, its sender's
  deletion (someone else's deletion leaves it alone), a group message, a
  new disappearing-message timer, and an admin's message (neither of the
  last two kept).

### Requested by the owner, 2026-10-23

- [x] Photo albums and photos by date, as planned: each folder directly
  inside `photos_dir` is an album (the owner's choice: not its subfolders,
  which are part of it), `/albums` lists them, and `/photo [<album>]
  [<date> [<time>]]`, `/onthisday [<album>]` and `/cache [<album>]` accept
  one; without an album, every photo is used (the owner's choice). The
  round is kept per album, as `/uniquephoto [<album>]` (in Swedish
  `/unikbild`), which replaced `/photo new`; timers and specials that ran
  `/photo new` are changed by hand, as the changelog says (the owner's
  choice, over rewriting them at startup). Each album's birth date, which
  `/album <album> <date>` sets and `/album <album> -` removes, is stored in
  `data_dir/albums.txt`, with `photos_birth_date` for albums without one
  (the owner's choice, over the bot writing config.toml). Albums visible to
  only some chats weren't requested. Measured: see Resource budget in
  CLAUDE.md.
- [x] A language for each person and each group, as planned: `/language`
  (in Swedish `/språk`), stored in `data_dir/languages.txt`. In a direct
  chat, it is for whoever sends it, everyone allowed included; a group's
  language, set there, is an admin's to change (the owner's choice); and an
  admin can set other chats' languages by their numbers in `/chats`, as in
  `/language 3,1 sv` (the owner's choice). Everything the bot says in a
  chat, and posts to it, is in its language, including the timers' and
  `/run`'s posts, reminders, the greeting, the notices and the outbox's
  notes. A timer runs its commands once per language, with one random draw,
  so every chat gets the same photo and the round uses up only one. Every
  language's command names and words are accepted from anyone, and `/help`
  shows the chat's. The weather's descriptions were already the bot's own,
  so only the names of places needed to vary by language. Measured: see
  Resource budget in CLAUDE.md.
- [x] `/today` without the weather, so that a special or a timer posts it
  with `/weather`: `/day` is another name for it (the owner's choice), and
  in posts, it is empty on a day with nothing (the owner's choice), so
  `/today; /weather` then posts just the weather. Timers and specials that
  ran `/today` alone are changed by hand, as the changelog says.
- [x] `/photo <date>` as precise as it is given: `2017`, `2017-05`,
  `2017-05-14` or `2017-05-14 15` at random, or else the nearest period of
  the same size that has photos; to the minute, the photo taken closest.
- [x] An album's own shortcuts for `/photo <album>`, in place of the
  configuration's aliases for `/photo`: `/album <album> shortcuts <names>`
  and `/album <album> shortcuts -`, stored in `albums.txt` with the birth
  dates. Measured: 10 µs more per alias lookup, about 26 µs in all, as each
  handler looks them up for each message.

### Requested by the owner, 2026-10-24

- [x] A `+` standing on its own joins a special's parts into one message,
  in place of a `;`: `/today + /weather` posts the day with the weather
  below it, as `/today` did before 0.99.14. Chosen over the `|` that the
  owner suggested, because `|` separates the name from the parts in the
  specials file and appears doubled in its spoiler marks. Everything the
  joined parts post goes into the one message, including both answers of a
  command that gives two, such as `/status`; a part on its own keeps its
  answers separate, as before. A `+` inside a word, as in `C++` or a phone
  number, remains text.
- [x] `/today` and `/day` say "Nothing special today." only when asked in a
  direct chat; in a group, and in what timers, specials and `/run` post,
  they say nothing on a day with nothing special.

### The day the images went to ghcr.io (done, 2026-10-18)

Releases since 0.93.2 are on ghcr.io, and since 0.93.5 on Docker Hub, both
public; the documentation and [deploy/](deploy) use
`docker.io/jodab/nejomibot:latest`, and each release attests its images
(step 5). How it was set up:

1. Raise the version, date the CHANGELOG, and push to GitHub. CI runs the
   checks and builds the image, without pushing it. On a private
   repository, that uses Actions minutes; on a public one, it is free.
2. Publish a release on GitHub, tagged `v` followed by the version, such as
   `v0.93.0`. The [release workflow](.github/workflows/release.yml) checks
   the tag against pyproject.toml, runs `tools/build-image.sh --source ...
   --push ghcr.io/OWNER/nejomibot`, and so pushes `:VERSION` and `:latest`
   for amd64, arm64 and arm/v7, labeled with the repository.
   [tools/release.sh](tools/release.sh) now does all of this.
3. On GitHub, make the package public (packages start out private).
4. Point the documentation and examples at it, instead of
   `localhost/nejomibot`.
5. Add build provenance, so that users can check where an image came from.

## Checked and fine

- No time bombs in the tests: they use fixed clocks, the one date in 2030
  isn't compared with today, and the example date is computed.
- signal-cli-rest-api isn't published in the examples; the admin commands
  rely on signalbot's contact filter, which checks both the number and the
  Signal ID; `/delete` checks for an admin itself in groups; and the allowed
  list is checked for every message.
- The container check can't put the bot in a restart loop while
  signal-cli-rest-api is down or misconfigured: the interval rounds record
  a result even before signalbot is ready.
- The image runs read-only, without capabilities and with an init process:
  it stops in a fraction of a second, and the tools work.
- Memory, measured on 2026-10-17: about 74 MB RSS after the imports and one
  picture opened, or 71 MB with `photos_heif = false`; mostly signalbot,
  aiohttp and pydantic.
- signalbot 2.1.3, the latest version on 2026-10-23, has nothing that would
  replace a function in rest.py, and doesn't mark sync messages: since
  2.1.0, it has only fixed a few things the bot doesn't use (copying a
  message, the order of a few fields' types, and a storage setting the bot
  doesn't use).
