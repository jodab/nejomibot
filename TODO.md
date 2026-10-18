# TODO

What's left of the review of all the code, tests, tools, image and deploy
examples on 2026-10-17 (nejomibot 0.92.0), worked through the same day:
[Open](#open) lists what still needs the owner, or someone upstream, and
plans that wait for them, such as accounts without a phone number;
[Done](#done) what was changed, and how. The changes are in
[CHANGELOG.md](CHANGELOG.md) under 0.93.0 and later.

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
- [ ] **More text styles in the posts?** (2026-10-18) The daily post's and
  the daily quote's headings are in bold, and the specials of your own keep
  Signal's formatting (see Done). Left to choose, as they change what people
  see: "Weather in {city}" in bold, and a proverb's explanation, the
  paragraph under it in `fortunes_svenska`, in italics. And `/special add`
  still refuses a typed `|` ("the file of specials uses it"), though only
  the first `|` of a line counts and the file now has spoilers' `||`:
  the refusal could go, the `|` kept as `\|`.

### For you to do

- [ ] **Perhaps say on 0.94.0's release page that its images are broken**
  (2026-10-18), and to use 0.94.1: `gh release edit v0.94.0 --notes-file
  ...`. It stays as published, as releases do.
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
- [ ] **Ask signal-cli-rest-api for signal-cli's version** (2026-10-18), for
  `/status` and the health check pings, which can't show it. Draft:
  *Say signal-cli's version in /v1/about.* `/v1/about` gives the REST API's
  own version (`BUILD_VERSION`, `unset` in CI builds) and the mode, not the
  signal-cli it runs, so a client can't tell which signal-cli answers it.
  The image knows it as it's built (`SIGNAL_CLI_VERSION`), and in json-rpc
  mode signal-cli answers a `version` request. A field such as
  `signal_cli_version` would do. signalbot's `About` would need the field
  too (it drops unknown ones); meanwhile `rest.py` could read it. Going
  around signal-cli-rest-api to signal-cli's own port (127.0.0.1:6001 in
  its container, which the bot reaches only because the examples share its
  network) isn't an API, so the bot doesn't.
### Accounts without a phone number

A plan, written 2026-10-18; nothing of it is done. The bot should run on an
account without a phone number, as one made with Signal Login is, and work
with people who have none.

**Where things stand** (2026-10-18):

- *Signal:* Signal Login, in Signal Android's beta since 8.28 (September
  2026), makes an account without a phone number for a one-time $3 through
  Google Play. Signal Android shows its Account Key, which is the account's
  ACI, a UUID such as `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, and a Recovery
  Key: nothing else brings the account back. Existing accounts can't drop
  their number, and without a username nobody can find the account.
- *signal-cli:* takes an ACI wherever it takes the account (`-a`,
  JSON-RPC's `account`) since 0.14.6. Since 0.14.9 it can link to an account
  without a number (signal-cli#2123), and recover one as its primary device:
  `register --recovery-key KEY -a ACI`, with `--totp` when Signal asks. It
  can't make one, as the payment is in the app store (signal-cli#2124,
  open). `listAccounts` gives `{"number": null, "aci": "..."}` (in text,
  `ACI: ...`), and what it receives carries the ACI as its `account`.
- *signal-cli-rest-api:* not yet; issue #889 is open, and someone there has
  a branch, for a PR once signal-cli 0.14.9 is in. Its paths take an ACI
  where they take `{number}`, and pass it to signal-cli, and its websocket
  picks messages by that `account`, so sending and receiving work: they
  linked such an account and sent from it. Missing: `/v1/accounts` lists
  only numbers, so such an account shows as `""`; the link's QR code is
  fixed at version 10, too small for the longer link; and `register` can't
  take a recovery key.
- *signalbot:* `Config.phone_number` is any string, used in the paths and
  as the sender, so the ACI should do. To try.

**Steps:**

1. Wait for signal-cli-rest-api's support, in a release or a CI build with
   signal-cli 0.14.9 or later, and pin it as now. Ask on #889 for what the
   bot needs besides: `/v1/accounts` listing the ACI of an account without a
   number, and `register` with `recovery_key` (and `totp`).
2. Yours to decide: an account for trying it ($3, an Android phone with
   Google Play and the beta), and how the bot takes it over. Recovered with
   its Recovery Key, signal-cli becomes its primary device, the phone gives
   it up, and the bot is the account's only device: the way to go. Linked,
   the phone keeps it, and what's typed there in a direct chat reaches the
   bot as the other person's, as with a number (Who may use what).
3. The code changes below, with tests.
4. Try it with the account on a signal-cli-rest-api of its own, posting to
   the test group only, then the docs.

**Code changes:**

- `config.py`: `account` takes a Signal ID already. Also take the Account
  Key as 32 hex digits without dashes, which signal-cli takes too (check how
  Signal Android shows it), and turn it into signal-cli's form, lowercase
  with dashes: the one its messages carry, which signal-cli-rest-api compares
  as text. Update the comment on `account`, which says a Signal ID may come
  once signal-cli-rest-api has accounts without a number.
- `bot.py`, `wait_for_account()`: `rest.accounts()` must find the ACI, in
  the form #889 lists it in. Its message says "account" already.
- `rest.py`: `accounts()` for the new list; each `account_path()` request
  tried with an ACI: devices, contacts, identities, trust, profiles,
  username, avatars.
- `profile.py`, `fetch_me()`: the fallback `Contact(number=account)` takes
  an ACI as a number; `uuid=` for one.
- `/profile` and `/status`: the ACI and the username where they show the
  number, and a warning when an account without a number has no username,
  as then nobody can find it.
- `account.py`, `allowed.py`: `Account.id`, `is_me()`, and the check that
  the bot can't allow itself, with an ACI in place of a number.
- `tools/signal-account.sh`: `use_account()` dies on anything but a number:
  take an ACI. `setup` and `register` offer recovery with the Account Key
  and the Recovery Key, asked for as PINs are, kept out of the history,
  saying that the phone gives the account up. `link` for an account without
  a number, once the QR code fits. `status` and `identities` show the ACI;
  `privacy` and `search` are about numbers, so they say so; `rate-limit --to`
  takes an ACI or `u:username`; `unregister` warns that an account without a
  number comes back only with its Recovery Key. Find out what `pin`, the
  registration lock, means without a number.
- People without a number: admins and the allowed list take Signal IDs
  already, and `admins` gets them from `signal-account.sh identities`.
  `/contacts add` takes only a phone number for someone the bot doesn't know
  yet: a username too, `u:name.42`, as signal-cli takes. That changes a
  command, so it's yours to decide.
- Tests: made-up ACIs; the config takes both forms, and gives the dashed
  one; the wait finds an account by its ACI; `fetch_me()`; `/status`'s
  lines; FakeApi answering for an account without a number.
- Docs: the README (Who may use what, Getting started, Configuration,
  Setting up and managing the Signal account), DOCKERHUB.md and
  config.example.toml: the bot needs an account of its own, a number it's
  registered with, or a Signal Login account, recovered into signal-cli;
  and with no number, a username.

### Upstream

- [ ] **signal-cli-rest-api is pinned to a CI build.** [deploy/](deploy) uses
  `1791633879-ci`, now by digest, as 0.101 is broken for the bot (#885, #892,
  signal-cli#2119); 0.101 was still the latest release on 2026-10-17, and on
  2026-10-18. Move to the next release once it's out, then revisit
  `LAST_TOO_OLD` in [health.py](nejomibot/health.py).
- [ ] **signal-cli-rest-api for accounts without a number** (#889, open):
  see Accounts without a phone number, above.

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
- [x] The health check pings say what runs, as `/status` does: the
  versions, the uptime and the memory. signal-cli's version can't be had:
  see For you to do.
- [x] A setup guide, step by step: the README's Getting started, and
  [DOCKERHUB.md](DOCKERHUB.md) for Docker Hub. Tried with the published
  images, up to registering, and with two likely mistakes.
- [x] Docker Hub's page is pushed by the release: DOCKERHUB.md as of the
  release, and the repository's description, by
  `peter-evans/dockerhub-description`, once the images are up, with a
  token that may delete (below). First done by 0.94.0's release.
- [x] Signed build provenance for each image a release pushes, keyless:
  `build-image.sh --digests` records what was pushed, by digest, and
  `actions/attest-build-provenance` attests it, for
  `gh attestation verify oci://IMAGE --repo jodab/nejomibot`. The digests
  were tried against a registry of our own. First done by 0.94.0's release:
  `gh attestation verify` takes both registries' images, each by its own
  digest, as built by release.yml at the tag, from its commit.
- [x] A config file the bot can't read, and a `data_dir` it can't write in,
  stop it with a message that says so, and as whom it runs. It said the
  file wasn't there, and went on without it.
- [x] `fortunes_svenska`'s source and terms: recorded in the README's
  License since the public release. It's the bot's own, proverbs and quotes
  from writers long dead in translations of its own, so it comes under the
  bot's license.
- [x] The Ruff extension is installed in VS Code (`charliermarsh.ruff`,
  2026-10-18), so this folder's settings format Python with it on save.
- [x] 0.94.0's images came out all amd64, labelled for the three
  platforms, each with arm/v7's variant: ubuntu-24.04's Podman 4.9 mixes up
  platforms when a stage names its own, as the uv stage does
  (`--platform=$BUILDPLATFORM`; podman#22730, buildah#4742). Reproduced
  with a small Containerfile: Podman 4.9.3 builds every platform on x86_64;
  5.7.0, on ubuntu-26.04, and 6.1.4 build each right. The image jobs run on
  `ubuntu-26.04` now, the release installs `qemu-user-binfmt` there (what
  `qemu-user-static` has become, with the F flag) and checks it, and
  `build-image.sh` stops before pushing unless each image runs as its
  platform, which catches both the 4.9.3 build and the labels. 0.94.1,
  released with it the same day, came out right: on both registries each
  platform's image is its own (the arm/v7 build took the release to under
  ten minutes), pulls for amd64, arm64 and arm/v7 find theirs, `latest` is
  the same manifest list as `0.94.1`, and both verify as attested.
- [x] A Docker Hub token that may read, write and delete, as
  `DOCKERHUB_TOKEN`: the 0.94.0 release's page job put DOCKERHUB.md on
  Docker Hub with it, and the repository's description.
- [x] Text styles in the posts (2026-10-18). "Photo of the day!" and
  "Proverb or quote of the day:" are in bold: the caption and the quote are
  styled, everything but the heading escaped, so a `~` in an OpenStreetMap
  link or a file name shows as it is. The specials of your own keep the
  formatting the admin gives their text in Signal, which signalbot hands
  over as `DataMessage.text_styles`: `styles.marked()` writes it as
  signal-cli-rest-api's marks, which `specials.txt` keeps, and reads them
  back as its `textstyleparser.go` does (`unmarked()`, tested against its
  own tests), so a mix the marks can't say is turned down rather than
  garbled. Stars go three at a time there, so `*a **b***` closes neither;
  spaces between bold and italic take neither, which keeps their stars
  apart, and leaves only those that meet inside a word. `***` needs
  signal-cli-rest-api 0.101 or later, which the bot does. Aliases move the
  styles with the text (`commands.resolved()`).

### The day images go to ghcr.io (done, 2026-10-18)

Releases since 0.93.2 are on ghcr.io, and since 0.93.5 on Docker Hub, both
public; the docs and [deploy/](deploy) use `docker.io/jodab/nejomibot:latest`,
and the release attests each image (step 5). How it was set up:

1. Bump the version and date the CHANGELOG, and push to GitHub. CI
   runs the checks and builds the image, without pushing it. On a private
   repository that takes Actions minutes; on a public one it's free.
2. Publish a release on GitHub, tagged `v` and the version, such as
   `v0.93.0`. [Release](.github/workflows/release.yml) checks the tag
   against pyproject.toml, runs `tools/build-image.sh --source ... --push
   ghcr.io/OWNER/nejomibot`, and so pushes `:VERSION` and `:latest` for
   amd64, arm64 and arm/v7, labelled with the repository.
   [tools/release.sh](tools/release.sh) does all of this now.
3. On GitHub, make the package public (packages start private).
4. Point the docs and examples at it, instead of `localhost/nejomibot`.
5. Build provenance, so users can check where an image came from.

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
- signalbot 2.1.0, still the latest on 2026-10-18, has nothing that would
  replace a function in rest.py, nor mark sync messages.
