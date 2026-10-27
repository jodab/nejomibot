# TODO

The open work, as of 0.99.27: decisions for the owner, what is planned,
plans that wait on them or on upstream projects, and what those projects
lack. What has been done is in [CHANGELOG.md](CHANGELOG.md).

## Decisions for you

- [ ] **When to move to 1.0.** Until then, every release is a patch release
  on 0.99.x, and `tools/release.sh` stops on minor and major releases:
  remove its guard (after the usage check) when the time comes.
- [ ] **Signal's own terms.** The code and the documentation should name
  things as Signal does. Signal Android's source (`lib/signal-login`) calls
  the credentials of an account registered without a phone number its
  Signal Login: an Account ID, which is the account's ACI, and a Recovery
  key. Signal never says "Signal ID", which is the bot's own name for
  anyone's ACI. The "Account Key" of Signal's 8.28 beta announcement is the
  Recovery key, not the ACI, as the README's
  [An account without a phone number](README.md#an-account-without-a-phone-number)
  and the comment on `account` in config.py have it. Decide what the bot's
  messages call an ACI: Account ID, as Signal does, or Signal ID. It appears
  in `/contacts`, `/status`, `/profile`, `/allow`, `/admin add`, the
  configuration's errors and `nejomibot-account`. Then make the code, the
  translations and the documentation use it throughout, and Signal's terms
  everywhere else.

## Accounts without a phone number

The bot should run on an account without a phone number, such as one
registered with a Signal Login, and work with people who have none.

**Where things stand:**

- *Signal:* Signal Android's beta, since 8.28, registers an account without
  a phone number for a one-time fee of $3 through Google Play. Its Signal
  Login is an Account ID, the account's ACI in upper case, such as
  `0F1E2D3C-4B5A-4968-8778-695A4B3C2D1E` (the bot takes either case), and a
  Recovery key: nothing else can restore the account. Signal Android shows
  them in the account settings of such an account only. Existing accounts
  can't drop their number, and without a username, nobody can find the
  account.
- *signal-cli* (0.14.9): accepts an ACI wherever it accepts the account,
  can link to an account without a number (signal-cli#2123), and can restore
  one as its primary device: `register --recovery-key KEY -a ACI`, with
  `--totp` when Signal asks for it. It can't create such an account, as the
  payment happens in the app store (signal-cli#2124).
- *signal-cli-rest-api:* the CI build that [deploy/](deploy) pins, and the
  owner's Raspberry Pi runs, has its numberless support (#896, 787d204e):
  its paths and its send requests take an ACI where they take the number,
  and `/v1/accounts` lists `{"number", "aci"}`. Its `register` can't take a
  Recovery key (or a `totp`), so it can only link such an account. Its
  websocket hears nothing for the ACI of an account with a number, as
  signal-cli names that account by its number. The owner's fork
  (jodab/signal-cli-rest-api, `numberless-account-ids`) mends both:
  `register` takes `recovery_key`, `totp` and `reregister`, and an ACI
  stands for its number.
- *signalbot:* passes `Config.phone_number` on only in paths and as the
  sender, so an ACI works, as far as the code goes.
- *The bot:* done, with tests against a fake signal-cli-rest-api: `account`
  takes a Signal ID; `/status` and `/profile` warn while an account without
  a number has no username; `nejomibot-account` matches an account by its
  number or ID, shows its Signal ID, skips the PIN and the number's privacy
  in `setup`, refuses `privacy`, notes what a PIN guards, warns before
  `unregister`, and restores the account with its Recovery key (`restore`,
  and `setup` for a Signal ID), where signal-cli-rest-api can; the README
  and config.example.toml describe it. The
  profile moves to a new account by itself: `bot.txt` keeps it.

**Steps:**

1. Done (2026-10-25): the owner restored an account without a number into
   signal-cli on the Pi, as the account's only device, and the bot runs on
   it.
2. Mostly done (2026-10-25): commands, groups, receipts and `/delivery`,
   the safety numbers, `/contacts`, `/profile`, the avatar, the username,
   and `signal-account.sh status` and `identities` (now `nejomibot-account`'s)
   all work on it. Still to
   find out, on a phone: whether a nickname for the bot takes away the "Name
   not verified" that Signal's apps mark its name with, as it can't be saved
   by number, and if so, say so in the README.
3. Find out what `pin`, the registration lock, does without a number. The
   restore itself isn't documented beyond the README's pointer to
   signal-cli: it waits for signal-cli-rest-api to restore accounts (see
   Upstream).

## Upstream

No issues are filed for these (the owner's decision): check each new release
of signalbot and signal-cli-rest-api for them.

- [ ] **signal-cli-rest-api's next release.** 0.101, the latest, is broken
  for the bot (#885, #892, signal-cli#2119), so [deploy/](deploy) pins the
  CI build `1792710189-ci` by digest, which the owner's Raspberry Pi runs
  too. Once a release is out, move to it and revisit `LAST_TOO_OLD` in
  [health.py](nejomibot/health.py).
  It will also give each websocket a buffer (68ca0107), so a burst of
  receipts is no longer cut short: then remove the note on that in
  delivery.py's docstring and in the README.
- [ ] **signalbot retries its start forever** on a signal-cli-rest-api it
  won't take: a version it can't read (as PEP 440) or older than
  `MIN_SIGNAL_CLI_REST_API_VERSION`, or a mode other than json-rpc. It logs
  a traceback each time, without saying what to do, and has no setting to
  skip the check. So `wait_for_account()` checks the same first
  (`health.refused_by_signalbot()`) and waits, saying why. Once signalbot
  says so itself, or takes any version, remove that check.
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
  server, with `nejomibot-account rate-limit --to <your number>`. Once
  signalbot passes the tokens on and can submit a solved captcha, decide
  whether an admin should be able to send the bot the `signalcaptcha://`
  link in a direct chat instead, which would be a new command.
- [ ] **signal-cli-rest-api can't restore an account with its Recovery
  key**: its `register` takes neither the key nor a TOTP, so only signal-cli
  itself can, and the owner's fork. `nejomibot-account restore` and `setup`
  send them already. Once a release takes them (the owner's request,
  2026-10-25):
  - Drop "which no release has yet" from the README, `nejomibot-account
    --help` and the changelog's note, and the README's pointer to
    signal-cli's own `register --recovery-key`.
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
- [ ] **Image signatures Podman can check.** Podman's `policy.json` matches
  a keyless Sigstore signature only by e-mail (`subjectEmail`), not by the
  workflow identity GitHub Actions signs with (container-libs#625, open).
  The images' signed build provenance covers the rest meanwhile (`gh
  attestation verify`). Once Podman can, sign the images with cosign in
  release.yml, and show `policy.json` in SECURITY.md.
- [ ] **Wheels for Python 3.15.** PyYAML, which signalbot needs, has none
  as of 6.0.3, so uv builds it from its source as the image is built: pure
  Python, without libyaml, in a few seconds, with the latest setuptools and
  Cython, which uv.lock doesn't pin. frozenlist, which aiohttp needs, has
  none as of 1.8.0, and runs as pure Python. Once a release of each has
  them, move to it.
- [ ] **What else signalbot lacks:** it puts a sync message's destination in
  a `DataMessage`'s source fields, so a command typed on a linked phone looks
  as if the other person had sent it (nejomibot-account and the README
  describe it as a drawback of linking; once signalbot tells sync messages
  apart, decide what the bot does with them); `SendError` keeps only the
  HTTP status, not signal-cli-rest-api's error text (`messages.describe()`);
  `SQLiteStorage` has no `close()` (the tests filter the ResourceWarning);
  and `MessageActions._log_send_errors` names the recipient at WARNING
  level.
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
