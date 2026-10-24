# TODO

The open work, as of 0.99.20: decisions for the owner, plans that wait on
them or on upstream projects, and what those projects lack. What has been
done is in [CHANGELOG.md](CHANGELOG.md).

## Decisions for you

- [ ] **When to move to 1.0.** Until then, every release is a patch release
  on 0.99.x, and `tools/release.sh` stops on minor and major releases:
  remove its guard (after the usage check) when the time comes.
- [ ] **An account to try without a phone number**: see the plan below,
  step 1.

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
- *signal-cli-rest-api:* supports such accounts in the CI build that
  [deploy/](deploy) pins, not yet in a release: its paths take an ACI where
  they take `{number}`, and `/v1/accounts` lists `{"number", "aci"}`. Its
  `register` can't take a Recovery Key (or a `totp`), so until it can, an
  account can only be linked.
- *signalbot:* `Config.phone_number` can be any string, used in the paths and
  as the sender, so an ACI should work; still to be tried.
- *The bot:* `account` takes a Signal ID, and finds the account by it; what
  remains is below.

**Steps:**

1. For you to decide: an account to try it with ($3, and an Android phone
   with Google Play and the beta), and how the bot takes it over. Restored
   with its Recovery Key, signal-cli becomes its primary device, the phone
   gives it up, and the bot is the account's only device: the way to go.
   Linked instead, the phone keeps the account, and what is typed there in a
   direct chat reaches the bot as if the other person had sent it, as with
   a number (see Who may use what in the README).
2. Make the code changes below, with tests.
3. Try it with the account on a signal-cli-rest-api of its own, posting only
   to the test group, then update the documentation.

**Code changes:**

- `rest.py`: every `account_path()` request tried with an ACI: devices,
  contacts, identities, trust, profiles, username and avatars.
- `delivery.expected()` takes the bot out of a group's members by its phone
  number only; without a number, it has to by its Signal ID.
- `/profile` and `/status`: warn when an account without a number has no
  username, since nobody can find it then. Check how Signal Android shows
  the Account Key, in case it is in another form.
- `tools/signal-account.sh`: `setup` and `register` should offer restoring
  with the Account Key and the Recovery Key, once signal-cli-rest-api can,
  asked for the way PINs are and kept out of the shell history, and say that
  the phone will give the account up. `link` for an account without a
  number. `status` and `identities` should show the ACI; `privacy` and
  `search` are about numbers, so they should say so; `rate-limit --to`
  should accept an ACI or `u:username`; and `unregister` should warn that
  an account without a number can only be restored with its Recovery Key.
  Find out what `pin`, the registration lock, means without a number.
- Tests: `/status`'s lines, and `FakeApi` answering for an account without a
  number throughout.
- Documentation: the README (Who may use what, Getting started,
  Configuration, Setting up and managing the Signal account), DOCKERHUB.md,
  config.example.toml and `signal-account.sh --help`: the bot needs an
  account of its own, either a number registered for it or a Signal Login
  account restored into signal-cli, and without a number, a username.

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

- [ ] **A typed command waits about 0.4 s before it runs.** `answer()` sends
  the read receipt, then shows the bot typing, each a request of about 0.2 s
  on the Pi, before the command starts. They could go out while the command
  runs, as long as the reply waits for them, once signal-cli-rest-api no
  longer crashes on overlapping requests (#885).
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
