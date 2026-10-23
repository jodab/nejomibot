# nejomibot

**A Signal bot for a family or a group of friends.** Every morning it can
post the weather and a photo from your photo library to your Signal groups,
and it answers a handful of commands. It speaks English and Swedish.

> **Disclaimer:** This project was created as a playground for teaching
> myself how to better use Claude Code, so everything you see here is
> entirely AI coded under my guidance.

- 🌤️ **A daily post:** the weather, then the photo of the day, at the time you choose,
  with the day's holidays, and in each group the birthdays and name days of those in it
- 📷 **`/photo`:** a random photo, with when it was taken and a map link, from every
  album or one, or from a year, month, day or moment; `/onthisday`, one from this
  day in an earlier year
- 🔔 **`/remind` and `/list`:** reminders, and a list such as for shopping, for each chat
- ⏰ **Timers:** any of its commands on a schedule, posted to the chats you choose
- 🔐 **Only the people and groups you allow** may use it; you manage it from Signal
- 🩺 **Health checks**, and a container health check

**Image:** `docker.io/jodab/nejomibot`, also `ghcr.io/jodab/nejomibot` ·
**Tags:** `latest`, and each release by its version ·
**Platforms:** linux/amd64, linux/arm64, linux/arm/v7 ·
**Source and docs:** [github.com/jodab/nejomibot](https://github.com/jodab/nejomibot) ·
**License:** GPL-3.0-or-later

## How it fits together

The bot talks to Signal through
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api), a
second container that holds the bot's Signal account. The two run side by
side, and the Compose file below sets them up so that nothing outside can
reach signal-cli-rest-api:

```
Signal  <-->  signal-cli-rest-api (the account)  <-->  nejomibot (the bot)
```

## Before you start

You need:

1. **A Linux machine that stays on**, such as a home server, a Raspberry Pi
   with a 64-bit system, or a small cloud server, with
   [Docker](https://docs.docker.com/engine/install/) and its Compose plugin:
   `docker compose version` should answer.
2. **A phone number for the bot, of its own.** It has to receive one text
   message or call, with a code. Not your own number, nor one that's in use
   with Signal on a phone: registering it for the bot signs it out of Signal
   everywhere else. A cheap prepaid SIM card will do; a landline can take the
   code as a call.
3. **Signal on your phone.** You'll be the bot's admin.
4. **A free [OpenWeatherMap](https://openweathermap.org/) API key**, for the
   weather: sign up, then copy the key from
   [your API keys](https://home.openweathermap.org/api_keys). A new key can
   take up to two hours to start working.
5. **Your photos**, in a folder: JPEG, PNG, GIF, WebP, AVIF or HEIC, in
   subfolders or not.
6. **A web browser**, on any computer or phone, for the captcha Signal asks
   for when you register the number.

Podman works too: type `podman` where this says `docker` (`podman compose`
needs podman-compose or Docker Compose installed), and see step 3. With
Podman and systemd, the
[Quadlets](https://github.com/jodab/nejomibot#podman-quadlets) are a better
fit: they also restart a container whose health check fails.

## Step 1: Make a folder for the bot

```sh
mkdir -p ~/nejomibot && cd ~/nejomibot
mkdir data photos signal
curl -fsSLO https://raw.githubusercontent.com/jodab/nejomibot/main/deploy/compose.yaml
```

- `data` is for the bot's settings, and what it keeps.
- `signal` is for the Signal account.
- `photos` is for your photos: copy them in. Or use your photo library where
  it is: in `compose.yaml`, change `./photos:/photos:ro` to the library's
  folder, such as `/srv/photos:/photos:ro`.

In `compose.yaml`, also change `TZ: Europe/Stockholm` to your time zone, for
the times in the log.

## Step 2: Write the settings

Copy the example settings out of the image, then open them in an editor:

```sh
docker run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > data/config.toml
nano data/config.toml
```

Fill in at least these, keeping the quotes:

| Setting | What it is | Example |
|---|---|---|
| `account` | The bot's phone number | `"+46700000000"` |
| `admins` | Your phone number: you'll be the admin | `["+46700000001"]` |
| `openweather_api_key` | Your OpenWeatherMap key | `"0123456789abcdef..."` |
| `weather_city` | The city for the weather | `"Stockholm"` |
| `timezone` | Your time zone, for the timers | `"Europe/Stockholm"` |
| `language` | `"en"` for English, `"sv"` for Swedish, `"el"` for Greek; a chat can choose its own with `/language` | `"en"` |

Phone numbers go in international format: `+`, the country code, then the
number without its first 0, and no spaces. In Sweden, 070-000 00 00 is
`+46700000000`.

Leave `signal_service` as it is: the Compose file sets it. `clocks` and
`exchange_rate` are for the `/info` command: change them, or delete those two
lines. The file explains every setting.

## Step 3: Hand the folders over

The bot runs as user 1001, and signal-cli-rest-api as user 1000, so each must
own its folder:

```sh
sudo chown -R 1001:1001 data && sudo chmod 700 data
sudo chown -R 1000:1000 signal
```

With rootless Podman, `podman unshare` does it instead of `sudo`:

```sh
podman unshare chown -R 1001:1001 data && podman unshare chmod 700 data
podman unshare chown -R 1000:1000 signal
```

From now on, edit the settings with `sudo nano data/config.toml` (with
Podman, `podman unshare nano data/config.toml`).

The bot only reads your photos, but it must be able to: they must be readable
by everyone (`chmod -R a+rX photos` makes them so).

## Step 4: Start it

```sh
docker compose up -d
docker compose logs -f nejomibot
```

The bot now waits for its Signal account, which you set up next. Its log
says so:

```
WARNING nejomibot.bot: signal-cli-rest-api at signal:8080 has no account +46700000000 yet: register or link it with signal-account.sh setup. Waiting.
```

That's as it should be. A line before it saying it can't reach
signal-cli-rest-api is fine too: that takes a few seconds to start. If it
says `Invalid configuration`, `Can't read` or `Can't write` instead, see
Troubleshooting, below. Press Ctrl+C to stop watching the log; the bot keeps
running.

## Step 5: Register the bot's number

The image comes with a tool for the Signal account. Start it, and answer its
questions:

```sh
docker compose exec nejomibot signal-account.sh setup
```

1. **Register or link?** Press Enter, for `r`: register. Don't link it to a
   phone (see Keep it safe, below).
2. **The captcha.** Signal almost always wants one first. Open
   [signalcaptchas.org/registration/generate.html](https://signalcaptchas.org/registration/generate.html)
   in a browser and solve it. When **Open Signal** shows, right-click it (on a
   phone, press and hold it) and copy the link. Paste it into the tool: it
   starts with `signalcaptcha://`, and works for a minute or so only.
3. **The code.** Signal texts a 6-digit code to the bot's number: type it in.
   If none comes within a minute, press Enter: the tool has Signal send it
   again, or call with it. If Signal can't send a text, the tool offers a
   call instead.
4. **Profile, username, PIN and privacy.** Enter skips any of them. Do give
   the bot a **name**, or Signal shows its number instead; and set a **PIN**
   (answer `y`), which stops anyone else from registering the number. Keep
   the PIN somewhere safe.

When the tool shows `== Done`, and the account under it, the bot starts
within seconds. Its log then has lines such as:

```
INFO nejomibot.bot: 0 chats on the allowed list, in /data/allowed.txt
INFO nejomibot.bot: 0 timers, in /data/timers.txt
INFO nejomibot.health: Checking the bot's health every 5 minutes
```

## Step 6: Say hello

On your phone, start a new chat in Signal with the bot's number (the pencil
button, then **Find by phone number**), and send it:

```
/help
```

It answers with the commands you may use. As its admin you may use them all,
the admin commands in this direct chat only. No answer within a minute? See
Troubleshooting, below.

## Step 7: Add the bot to your groups

1. In Signal on your phone, open a group, tap its name, then **Add members**,
   and pick the bot. Do it after the bot has answered you: then it joins at
   once. Before that, Signal may only invite it, and the bot doesn't take up
   invitations.
2. In your direct chat with the bot, allow the group, by its name:

   ```
   /allow Family
   ```

   Everyone in the group may now use the everyday commands there: `/photo`,
   `/weather`, `/forecast`, `/remind`, `/list`, `/help` and more.
3. To let someone use the bot in a direct chat with it, allow them by their
   number: `/allow +46700000002`.

`/allowed` shows who may use it, numbered; `/disallow 2` takes number 2 off
the list.

## Step 8: Schedule the daily post

Send the bot:

```
/chats
/timer add 08:00 1 /today; /weather; /uniquephoto
/timer run 1
```

- `/chats` numbers the chats the bot can post to: its groups, then the people
  allowed, then you.
- `/timer add 08:00 1 /today; /weather; /uniquephoto` posts the day's
  holidays and birthdays, once there are some, the weather, then a photo,
  none twice until every one has been sent, at 08:00 every day, in your
  `timezone`, to chat 1. For more chats, give them all: `1,2`. Days work
  too: `mon-fri 07:30`.
- `/timer run 1` posts it right away, so you see that it works. `/timers`
  lists the timers.

That's it: the bot is up and running. 🎉

## More you can do

- **A profile picture:**
  `docker compose exec -T nejomibot signal-account.sh profile --avatar - < picture.jpg`
- **Be warned when it's down:** make a check at
  [healthchecks.io](https://healthchecks.io), and put its ping URL in
  `healthcheck_url` in the settings. The bot pings it every 5 minutes, saying
  what it found.
- **See how it's doing:** send it `/status`. `docker compose ps` shows the
  containers as `healthy` a minute after they start (with Podman,
  `podman ps` does).
- **Birthdays, name days and holidays, for `/today`:** `/birthday add
  1990-03-14 Alice` for a contact, shown in the groups they're in, and
  `holidays = ["SE"]` in the settings for your country's days, by its code,
  such as `GB` or `US`: the European Union's, the Nordic countries' and most
  of the West's are there; see
  [the README](https://github.com/jodab/nejomibot#birthdays-name-days-and-holidays).
- **Backups:** every day at 04:00 the bot backs up what it keeps, and its
  settings, in `data/backups`, unless nothing changed, and keeps the latest
  30; see [the README](https://github.com/jodab/nejomibot#backups).
- **Commands of your own, other names for commands, and all the settings:**
  see the [README](https://github.com/jodab/nejomibot#readme).

## Updating

```sh
docker compose pull && docker compose up -d
```

Read the [changelog](https://github.com/jodab/nejomibot/blob/main/CHANGELOG.md)
first: it says if there's anything to do. If a setting has to change, the bot
says which in its log, and doesn't start until it's changed. To choose when
to update, give the image a version in `compose.yaml` in place of `latest`,
from the Tags tab.

## Keep it safe

- **Never publish signal-cli-rest-api's port, 8080.** It has no password:
  anyone who reaches it controls the bot's Signal account. The Compose file
  publishes nothing.
- **Give the bot a number of its own, and register it; don't link it to your
  phone.** Linked to a phone, what you type there in a direct chat with
  someone reaches the bot as if they had sent it, admin commands too.
- **Keep `data` private.** It holds your API key and phone numbers; step 3
  makes it the bot's alone.

## Troubleshooting

**The log says `Invalid configuration (config file: /data/config.toml):`**
and then a setting, such as `admins.0: Value error, '0700000001' is neither a
phone number (+…) nor a Signal ID`. Fix that setting
(`sudo nano data/config.toml`), then `docker compose restart nejomibot`.

**The log says `Can't read the config file /data/config.toml: Permission denied`,
or `Can't write in data_dir /data: Permission denied`.** The `data` folder
isn't the bot's: do step 3 again.

**The bot doesn't answer you.**

1. Look at its log, `docker compose logs nejomibot`: it must be past
   `Waiting`.
2. Check that `admins` has your number, in international format.
3. Still nothing? Your Signal may not show your number to the bot, as it
   doesn't when *Settings > Privacy > Phone number > Who can see my number*
   is *Nobody*. Then the bot knows you by your Signal ID. List who has
   written to the bot, and find yourself by your name:

   ```sh
   docker compose exec nejomibot signal-account.sh identities
   ```

   Put the ID after your name, which looks like
   `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, in `admins` in place of your
   number, in quotes: `admins = ["0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"]`.
   Then `docker compose restart nejomibot`.

**A group isn't in `/chats`, and `/allow` can't find it.** Signal only
invited the bot. In the group's settings, under **Requests & invites**,
revoke its invite. Then, once the bot has answered you in your direct chat
with it, add it again.

**`/weather` says `OpenWeatherMap answered with an error (401: Invalid API key...)`.**
A new key takes up to two hours to start working. Check that the key in the
settings is the one on your API keys page.

**The captcha didn't work.** It's only good for a minute or so: solve a new
one, and paste the link right away.

**No code comes.** Press Enter where the tool asks for it, and it has Signal
send the code again, or call with it. Signal's first text sometimes never
comes, while the next one does at once. Signal limits how often a number can
ask for a code: if it keeps saying no, wait a while before trying again.

**On Fedora, RHEL and other systems with SELinux**, the containers may be
refused their folders. In `compose.yaml`, add `:Z` to the data and signal
folders (`./data:/data:Z`, `./signal:/home/.local/share/signal-cli:Z`), and
`,z` to the photos' (`./photos:/photos:ro,z`).

**Still stuck?** [Open an issue](https://github.com/jodab/nejomibot/issues).

## Where the image comes from

Each release's images are built and pushed by the repository's own release
workflow on GitHub, from the release's commit, with signed build provenance
(releases after 0.93.5). With the [GitHub CLI](https://cli.github.com/),
logged in, check that an image is one of them:

```sh
gh attestation verify oci://docker.io/jodab/nejomibot:latest --repo jodab/nejomibot
```

It shows the workflow that built it, and from which commit.

## Learn more

- [The README](https://github.com/jodab/nejomibot#readme): every command,
  the allowed list, timers, specials, languages and settings
- [The health checks](https://github.com/jodab/nejomibot#health-checks)
- [Running it with Podman Quadlets](https://github.com/jodab/nejomibot#podman-quadlets)
- [The changelog](https://github.com/jodab/nejomibot/blob/main/CHANGELOG.md)
