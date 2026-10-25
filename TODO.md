# TODO

The open work, as of 0.99.26: decisions for the owner, what is planned,
plans that wait on them or on upstream projects, and what those projects
lack. What has been done is in [CHANGELOG.md](CHANGELOG.md).

## Decisions for you

- [ ] **When to move to 1.0.** Until then, every release is a patch release
  on 0.99.x, and `tools/release.sh` stops on minor and major releases:
  remove its guard (after the usage check) when the time comes.

## Planned

- [ ] **`/help <command>`, a command's help in full** (the owner's request,
  2026-10-25): what the command does and what may follow it, in a few
  lines, with examples of its use, in the chat's language, for a command
  the asker may use, as `/help` lists them; by its name in any language, an
  alias or a shortcut, starting with `.` or `/` as every command may.
  `/help` takes nothing after it now. The README's tables and the usage
  text each command answers when it can't make out what follows it
  (`photo_usage()`, `username_usage()` and the rest) are where to start,
  and a test should check that every command has its help, as one does
  for its line in `/help`.

## Accounts without a phone number

The bot should run on an account without a phone number, such as one
created with Signal Login, and work with people who have none.

**Where things stand:**

- *Signal:* Signal Login, in Signal Android's beta since 8.28, creates an
  account without a phone number for a one-time fee of $3 through Google
  Play. Signal Android shows its Account Key, the account's ACI, a UUID such
  as `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, and a Recovery Key: nothing else
  can restore the account. Existing accounts can't drop their number, and
  without a username, nobody can find the account.
- *signal-cli* (0.14.9): accepts an ACI wherever it accepts the account,
  can link to an account without a number (signal-cli#2123), and can restore
  one as its primary device: `register --recovery-key KEY -a ACI`, with
  `--totp` when Signal asks for it. It can't create such an account, as the
  payment happens in the app store (signal-cli#2124).
- *signal-cli-rest-api:* the CI build that [deploy/](deploy) pins, and the
  owner's Raspberry Pi runs, has its numberless support (#896, 787d204e):
  its paths and its send requests take an ACI where they take the number,
  and `/v1/accounts` lists `{"number", "aci"}`. Its `register` can't take a
  Recovery Key (or a `totp`), so it can only link such an account.
- *signalbot:* passes `Config.phone_number` on only in paths and as the
  sender, so an ACI works, as far as the code goes.
- *The bot:* done, with tests against a fake signal-cli-rest-api: `account`
  takes a Signal ID; `/status` and `/profile` warn while an account without
  a number has no username; `signal-account.sh` matches an account by its
  number or ID, shows its Signal ID, skips the PIN and the number's privacy
  in `setup`, refuses `privacy`, notes what a PIN guards, and warns before
  `unregister`; the README, DOCKERHUB.md and config.example.toml describe
  it. The profile moves to a new account by itself: `bot.txt` keeps it.

**Steps:**

1. Done (2026-10-25): the owner restored an account without a number into
   signal-cli on the Pi, as the account's only device, and the bot runs on
   it.
2. Try the bot on it, posting only to the test group: commands, receipts
   and `/delivery`, the safety numbers, `/contacts`, `/profile`, the
   avatar, `signal-account.sh status` and `identities`, and whether Signal
   Android shows the Account Key as the ACI, in case it's in another form.
   Signal's apps mark the bot's name "Name not verified", as it can't be
   saved by number: find out whether a nickname for the bot takes that
   away, and if so, say so in the README.
3. Write the restore down in the README once it has worked, and find out
   what `pin`, the registration lock, does without a number.

## Upstream

No issues are filed for these (the owner's decision): check each new release
of signalbot and signal-cli-rest-api for them.

- [ ] **signal-cli-rest-api's next release.** 0.101, the latest, is broken
  for the bot (#885, #892, signal-cli#2119), so [deploy/](deploy) pins the
  CI build `1792710189-ci` by digest; the owner's Raspberry Pi stays on
  0.101, as the CI builds have issues of their own. Once a release is out,
  move to it and revisit `LAST_TOO_OLD` in [health.py](nejomibot/health.py).
  It will also give each websocket a buffer (68ca0107), so a burst of
  receipts is no longer cut short: then remove the note on that in
  delivery.py's docstring and in the README.
- [ ] **signalbot drops receipts**: its parser knows no receipt message
  (`UnknownMessageFormatError`, skipped), so
  [delivery.py](nejomibot/delivery.py) receives them on a websocket of its
  own, `rest.received()`. Once signalbot has a receipt message type and a
  handler for it, use those, and remove the second websocket.
- [ ] **signalbot can't lift a rate limit**: a failed send's `SendError`
  keeps only the HTTP status, not the `challenge_tokens` that come with
  signal-cli-rest-api's 429, and signalbot makes no request to
  `/v1/accounts/{number}/rate-limit-challenge` (as of 2.2.0, its
  `RateLimitChallengeRequest` is only a model generated from
  signal-cli-rest-api's swagger.json). So the admins lift a limit on the
  server, with `signal-account.sh rate-limit --to <your number>`. Once
  signalbot passes the tokens on and can submit a solved captcha, decide
  whether an admin should be able to send the bot the `signalcaptcha://`
  link in a direct chat instead, which would be a new command.
- [ ] **signal-cli-rest-api can't restore an account with its Recovery
  Key**: its `register` takes neither the key nor a TOTP, so only signal-cli
  itself can. Once it can (the owner's request, 2026-10-25):
  - `signal-account.sh setup` restores the account, with the key asked for
    as PINs are, or read from a file such as a Podman or Docker secret
    (`/run/secrets/...`), never from the config or the environment, which
    `podman inspect`, logs and process lists show.
  - The bot may restore its account as it starts, with its Signal ID from
    `account` and the key from such a file, but only when
    signal-cli-rest-api has no account at all, as on a new install: never to
    mend one that fails, as it can't tell that from signal-cli-rest-api
    being down or its volume missing (a registration into an empty store
    would cut the real one off), Signal may ask for a TOTP that a person
    has to give, and registrations are rate-limited.
  - At rest, Podman's secrets are files only root can read, not encrypted,
    and Docker Compose's are plain files; systemd's encrypted credentials
    (`systemd-creds`) need the host's key, so a copy of the file alone is
    useless. None keeps the key from root on the host, which can read the
    copy signal-cli keeps in its data folder after a restore anyway; the key
    is safest off the server, in a password manager.
  - A backup of signal-cli-rest-api's data folder, taken while it's stopped
    (a copy of its database in use may not open) and kept encrypted, brings
    the same account back: its identity, so the bot's safety number stays,
    and its registration, profile and groups. Its sessions, which change
    with every message, are as old as the backup, so messages around a
    restore may fail until the senders' apps start new sessions, which they
    do by themselves; and two copies of the account must never run at once.
    Find out whether a restore from the Recovery Key keeps the safety number,
    or every contact sees it change: a "safety number changed" notice in a
    chat with the bot after the owner's restore of 2026-10-25 would tell.
- [ ] **Wheels for Python 3.15.** PyYAML, which signalbot needs, has none
  as of 6.0.3, so uv builds it from its source as the image is built: pure
  Python, without libyaml, in a few seconds, with the latest setuptools and
  Cython, which uv.lock doesn't pin. frozenlist, which aiohttp needs, has
  none as of 1.8.0, and runs as pure Python. Once a release of each has
  them, move to it.
- [ ] **What else signalbot lacks:** it puts a sync message's destination in
  a `DataMessage`'s source fields, so a command typed on a linked phone looks
  as if the other person had sent it (the bot warns against linking
  instead); `SendError` keeps only the HTTP status, not signal-cli-rest-api's
  error text (`messages.describe()`); `SQLiteStorage` has no `close()` (the
  tests filter the ResourceWarning); `MessageActions._log_send_errors` names
  the recipient at WARNING level; and it depends on phonenumbers, 41 MB,
  where phonenumberslite would do (uv's `exclude-dependencies` swaps them).
  A received message its models can't validate (pydantic's
  `ValidationError`, which its receiving doesn't catch, unlike
  `UnknownMessageFormatError`), or a failed group refresh, ends its
  receiving: `rerun_on_exception` starts it again after 1 second, doubling
  up to 5 minutes, and prints the traceback to stderr, outside the bot's
  log; what arrives meanwhile may not reach the bot.
  Nor does signal-cli-rest-api's `/v1/about` give signal-cli's version, so
  `/status` and the health check pings can't show it.

## Waiting

- [ ] **A message that signal-cli-rest-api always refuses holds up its
  chat.** An HTTP 400 counts as surely not sent, so the message is tried
  again every 2 minutes for `send_retry_hours` (3 by default), and every
  later message to that chat waits behind it. A message refused for a
  changed safety number should wait until an admin trusts it, and the bot
  can't tell that refusal from one that never passes until signalbot passes
  signal-cli-rest-api's error text on (see above).
- [ ] **The calendar needs upkeep**: Sweden's flag days for the royal family
  are tied to the people who have them now (förordning 1982:270), and change
  with a new monarch; New Zealand's Matariki dates are listed up to 2052.
