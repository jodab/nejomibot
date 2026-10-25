# nejomibot

**A self-hosted Signal bot for a family or a group of friends.** Every
morning it can greet your groups with the day's holidays, birthdays and name
days, the weather, and a photo from your own photo library. Throughout the
day, it answers everyday commands for photos, the weather, reminders and
shared lists, and it runs whatever else you schedule. You run it on your own
machine, such as a home server or a Raspberry Pi, and manage it entirely from
Signal.

> **Disclaimer:** This project began as a playground for teaching myself to
> make better use of Claude Code. Everything here was written by AI, under my
> guidance.

- 🌅 **A daily post** at the time you choose: the day's holidays, flag days
  and traditions in any of 35 countries, each group's birthdays and name
  days, the weather, and a photo of the day, never the same photo twice until
  every one has been shown.
- 📷 **Your photo library in Signal:** a random photo from all albums or just
  one, a photo from a given year, month, day or moment, and one taken on this
  day in an earlier year, each with when and where it was taken and, if you
  like, the age of the person in it.
- 🌦️ **The weather and more:** the current weather and a two-day forecast for
  any place, world clocks and an exchange rate, and proverbs, quotes and
  fortunes.
- 🔔 **Reminders and shared lists** for each chat, such as a shopping list for
  the whole family.
- ⏰ **Timers and commands of your own:** any command on a schedule, posted to
  the chats you choose, and your own commands that combine texts and other
  commands, such as a morning greeting, for the admins or for everyone.
- 🌍 **Nine languages:** English, Danish, Finnish, French, German, Greek,
  Norwegian, Spanish and Swedish, with each chat in its own language.
- 🔐 **Private by design:** only the people and groups you allow may use it,
  admins manage it from a direct chat, and by default, the log contains no
  phone numbers or message text.
- 🩺 **Reliable and light:** health checks with alerts, notices to the admins,
  messages retried until they get through, and a small image that runs in
  about 80 MB of memory.

**Image:** `docker.io/jodab/nejomibot`, also `ghcr.io/jodab/nejomibot` ·
**Tags:** `latest`, and each release by its version ·
**Platforms:** linux/amd64, linux/arm64, linux/arm/v7 ·
**Source and documentation:** [github.com/jodab/nejomibot](https://github.com/jodab/nejomibot) ·
**License:** MIT

## How it fits together

The bot talks to Signal through
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api), a
second container that holds the bot's Signal account. The two run side by
side, and the Compose file below sets them up so that nothing outside them
can reach signal-cli-rest-api:

```
Signal  <-->  signal-cli-rest-api (the account)  <-->  nejomibot (the bot)
```

## Before you start

You need:

1. **A Linux machine that is always on**, such as a home server, a Raspberry
   Pi with a 64-bit or 32-bit operating system, or a small cloud server, with
   [Docker](https://docs.docker.com/engine/install/) and its Compose plugin
   installed: `docker compose version` should print a version. The bot and
   signal-cli-rest-api together use about 450 MB of memory.
2. **A phone number for the bot alone.** It must be able to receive one text
   message or call with a verification code. Don't use your own number, or
   any number that is in use with Signal on a phone: registering it for the
   bot signs it out of Signal everywhere else. A cheap prepaid SIM card
   works, and a landline can receive the code as a voice call.
3. **Signal on your phone.** You will be the bot's admin.
4. **A free [OpenWeatherMap](https://openweathermap.org/) API key** for the
   weather: sign up, then copy the key from
   [your API keys page](https://home.openweathermap.org/api_keys). A new key
   can take up to two hours to become active.
5. **Your photos** in a folder, as JPEG, PNG, GIF, WebP, AVIF or HEIC files,
   with or without subfolders.
6. **A web browser** on any computer or phone, to solve the captcha that
   Signal requires when you register the number.

Podman works too: type `podman` wherever this guide says `docker`
(`podman compose` requires podman-compose or Docker Compose to be
installed), and see step 3. If you use Podman with systemd, the
[Quadlets](https://github.com/jodab/nejomibot#podman-quadlets) are a better
fit, because they also restart a container whose health check fails.

## Step 1: Create a folder for the bot

```sh
mkdir -p ~/nejomibot && cd ~/nejomibot
mkdir data photos signal
curl -fsSLO https://raw.githubusercontent.com/jodab/nejomibot/main/deploy/compose.yaml
```

- `data` holds the bot's settings and everything it stores.
- `signal` holds the Signal account.
- `photos` holds your photos: copy them in. Alternatively, use your photo
  library where it is: in `compose.yaml`, change `./photos:/photos:ro` to the
  library's folder, for example `/srv/photos:/photos:ro`.

In `compose.yaml`, also change `TZ: Europe/Stockholm` to your time zone,
which sets the times shown in the log.

## Step 2: Write the settings

Copy the example settings out of the image, then open them in an editor:

```sh
docker run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > data/config.toml
nano data/config.toml
```

Fill in at least the following settings, keeping the quotes:

| Setting | Description | Example |
|---|---|---|
| `account` | The bot's phone number, or the Signal ID of [an account without one](https://github.com/jodab/nejomibot#an-account-without-a-phone-number) | `"+46700000000"` |
| `admins` | Your phone number, which makes you the admin | `["+46700000001"]` |
| `openweather_api_key` | Your OpenWeatherMap API key | `"0123456789abcdef..."` |
| `weather_city` | The city for the weather | `"Stockholm"` |
| `timezone` | Your time zone, used by the timers | `"Europe/Stockholm"` |
| `language` | The bot's language: `"en"` (English), `"da"` (Danish), `"de"` (German), `"el"` (Greek), `"es"` (Spanish), `"fi"` (Finnish), `"fr"` (French), `"nb"` (Norwegian) or `"sv"` (Swedish); each chat can choose its own with `/language` | `"en"` |

Write phone numbers in international format: a `+`, the country code, then
the number without its leading 0, with no spaces. In Sweden, 070-000 00 00
becomes `+46700000000`.

Leave `signal_service` as it is, because the Compose file sets it. `clocks`
and `exchange_rate` are used by the `/info` command: change them, or delete
those two lines. The file explains every setting.

## Step 3: Set the folder ownership

The bot and signal-cli-rest-api both run as user 1000, so that user must own
both folders:

```sh
sudo chown -R 1000:1000 data signal && sudo chmod 700 data
```

With rootless Podman, use `podman unshare` instead of `sudo`:

```sh
podman unshare chown -R 1000:1000 data signal && podman unshare chmod 700 data
```

To run the bot as another user, give its user and group in `compose.yaml`,
as `user: "1001:1001"`, and have that user own `data` instead.

From now on, edit the settings with `sudo nano data/config.toml` (with
Podman, `podman unshare nano data/config.toml`).

The bot only reads your photos, but it must be able to: they must be
readable by everyone (`chmod -R a+rX photos` makes them so).

## Step 4: Start the bot

```sh
docker compose up -d
docker compose logs -f nejomibot
```

The bot now waits for its Signal account, which you set up in the next
step, and its log says so:

```
WARNING nejomibot.bot: signal-cli-rest-api at signal:8080 has no account +46700000000 yet: register or link it with signal-account.sh setup. Waiting.
```

This is expected. An earlier line saying that the bot can't reach
signal-cli-rest-api is also fine: signal-cli-rest-api takes a few seconds to
start. If the log says `Invalid configuration`, `Can't read` or `Can't
write` instead, see Troubleshooting below. Press Ctrl+C to stop following
the log; the bot keeps running.

## Step 5: Register the bot's number

The image includes a tool for managing the Signal account. Start it, and
answer its questions:

```sh
docker compose exec nejomibot signal-account.sh setup
```

If the bot isn't running, run the tool in a container of its own instead:
`docker compose run --rm nejomibot signal-account.sh setup`.

1. **Register or link?** Press Enter to choose `r`, register. Don't link the
   bot to a phone (see Keep it safe, below).
2. **The captcha.** Signal almost always requires one first. Open
   [signalcaptchas.org/registration/generate.html](https://signalcaptchas.org/registration/generate.html)
   in a browser and solve the captcha. When **Open Signal** appears,
   right-click it (on a phone, press and hold it) and copy the link. Paste it
   into the tool: it starts with `signalcaptcha://`, and it is valid for only
   about a minute.
3. **The code.** Signal texts a 6-digit code to the bot's number: enter it.
   If no code arrives within a minute, press Enter, and the tool asks Signal
   to send it again or to call with it. If Signal can't send a text message,
   the tool offers a call instead.
4. **Profile, username, PIN and privacy.** Press Enter to skip any of these.
   Do give the bot a **name**, or Signal shows its phone number instead, and
   set a **PIN** (answer `y`), which prevents anyone else from registering
   the number. Keep the PIN somewhere safe.

When the tool shows `== Done` followed by the account, the bot starts within
seconds. Its log then shows lines such as:

```
INFO nejomibot.bot: 0 chats on the allowed list, in /data/allowed.txt
INFO nejomibot.bot: 0 timers, in /data/timers.txt
INFO nejomibot.health: Checking the bot's health every 5 minutes
```

## Step 6: Say hello

On your phone, start a new chat in Signal with the bot's number (tap the
pencil button, then **Find by phone number**), and send it:

```
/help
```

The bot replies with the commands you may use. As its admin, you may use all
of them, but the admin commands only in this direct chat. `/help` and a
command, as in `/help timer`, explains that command, with examples. No reply
within a minute? See Troubleshooting below.

Every command can start with a period instead of the slash, as in `.help`,
which phone keyboards have on their first page; the bot's replies show
commands that way.

## Step 7: Add the bot to your groups

1. In Signal on your phone, open a group, tap its name, tap **Add members**,
   and select the bot. Do this after the bot has replied to you, so that it
   joins right away. Before that, Signal may only invite it, and the bot
   doesn't accept invitations.
2. In your direct chat with the bot, allow the group by name:

   ```
   /allow Family
   ```

   Everyone in the group can now use the everyday commands in that group:
   `/photo`, `/weather`, `/forecast`, `/remind`, `/list`, `/help` and more.
3. To let someone use the bot in a direct chat with it, allow them by their
   number: `/allow +46700000002`.

`/allowed` shows who may use the bot, numbered; `/disallow 2` removes number
2 from the list.

## Step 8: Schedule the daily post

Send the bot:

```
/chats
/timer add 08:00 1 /today; /weather; /uniquephoto
/timer run 1
```

- `/chats` numbers the chats the bot can post to: its groups first, then the
  people you have allowed, then you.
- `/timer add 08:00 1 /today; /weather; /uniquephoto` posts to chat 1 at
  08:00 every day, in your `timezone`: the date and time with the day's
  holidays and birthdays, the weather, and a photo, never the same photo
  twice until every photo has been sent. For several chats, list them all: `1,2`.
  You can also give days: `mon-fri 07:30`.
- `/timer run 1` runs the timer right away, so you can see that it works.
  `/timers` lists the timers.

That's it: the bot is up and running. 🎉

## More you can do

- **A profile picture:**
  `docker compose exec -T nejomibot signal-account.sh profile --avatar - < picture.jpg`
- **Get alerted when the bot is down:** create a check at
  [healthchecks.io](https://healthchecks.io), and put its ping URL in
  `healthcheck_url` in the settings. The bot pings it every 5 minutes with
  what it found.
- **See how the bot is doing:** send it `/status`. `docker compose ps` shows
  the containers as `healthy` a minute after they start (with Podman,
  `podman ps` does).
- **The day in one message:** `/special add /dailypost /today + /weather;
  Photo of the day! /uniquephoto` creates a command of your own that posts
  the day and the weather in one message, then the photo under a heading;
  run it from the timer with `/timer add 08:00 1 /dailypost`, and give it a
  shorter name with `/special shortcuts /dailypost /daily`.
  `/special everyone /dailypost` lets everyone you have allowed use it too,
  in groups as well, and `/help` lists it for them.
- **Birthdays, name days and holidays for `/today`:** `/birthday add
  1990-03-14 Alice` adds a contact's birthday, shown in the groups they are
  in, `/nameday add 08-08 1,2 Grandma` the name day of someone not on Signal,
  shown in chats 1 and 2 of `/chats`, and `holidays = ["SE"]` in the
  settings adds your country's days, by its code, such as `GB` or `US`:
  those of the European Union, the Nordic countries and most of the Western
  world are included; see
  [the README](https://github.com/jodab/nejomibot#birthdays-name-days-and-holidays).
- **A shell in the container:** `docker compose exec nejomibot sh`, or
  `bash`, starts with a short guide to the bot's tools, such as
  `nejomibot-timers` and `signal-account.sh`, and where the bot keeps its
  files.
- **Commands of your own, other names for commands, and all the settings:**
  see the [README](https://github.com/jodab/nejomibot#readme).

## Updating

```sh
docker compose pull && docker compose up -d
```

Read the [changelog](https://github.com/jodab/nejomibot/blob/main/CHANGELOG.md)
first: it says whether there is anything to do. If a setting has to change,
the bot says which one in its log, and doesn't start until it has been
changed. To choose when to update, replace `latest` in `compose.yaml` with a
version from the Tags tab.

## Keep it safe

- **Never publish signal-cli-rest-api's port, 8080.** It has no password:
  anyone who can reach it controls the bot's Signal account. The Compose
  file publishes nothing.
- **Give the bot an account of its own, and register it; don't link it to
  your phone.** When the bot is linked to a phone, anything typed there in a
  direct chat with someone reaches the bot as if that person had sent it,
  admin commands included.
- **Keep `data` private.** It holds your API key and phone numbers; step 3
  makes it accessible to the bot alone.

## Troubleshooting

**The log says `Invalid configuration (config file: /data/config.toml):`**
followed by a setting, such as `admins.0: Value error, '0700000001' is
neither a phone number (+…) nor a Signal ID`. Correct that setting (`sudo
nano data/config.toml`), then run `docker compose restart nejomibot`.

**The log says `Can't read the config file /data/config.toml: Permission
denied`, or `Can't write in data_dir /data: Permission denied`.** The `data`
folder doesn't belong to the bot: repeat step 3.

**The bot doesn't reply.**

1. Look at its log, `docker compose logs nejomibot`: it must be past the
   `Waiting` line.
2. Check that `admins` contains your number, in international format.
3. Still nothing? Your Signal may be hiding your number from the bot, as it
   does when *Settings > Privacy > Phone number > Who can see my number* is
   set to *Nobody*. The bot then knows you only by your Signal ID. List
   everyone who has written to the bot, and find yourself by name:

   ```sh
   docker compose exec nejomibot signal-account.sh identities
   ```

   Put the ID shown after your name, which looks like
   `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, in `admins` in place of your
   number, in quotes: `admins = ["0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"]`.
   Then run `docker compose restart nejomibot`.

**A group is missing from `/chats`, and `/allow` can't find it.** Signal
only invited the bot. In the group's settings, under **Requests & invites**,
revoke the invitation. Then, once the bot has replied to you in your direct
chat with it, add it again.

**`/weather` says `OpenWeatherMap answered with an error (401: Invalid API
key...)`.** A new key takes up to two hours to become active. Check that the
key in the settings is the one shown on your API keys page.

**The captcha didn't work.** A captcha is valid for only about a minute:
solve a new one, and paste the link right away.

**No code arrives.** Press Enter when the tool asks for the code, and it
asks Signal to send it again or to call. Signal's first text message
sometimes never arrives, while the next one arrives at once. Signal limits
how often a number can request a code: if it keeps refusing, wait a while
before trying again.

**On Fedora, RHEL and other systems with SELinux**, the containers may be
denied access to their folders. In `compose.yaml`, add `:Z` to the data and
signal volumes (`./data:/data:Z`, `./signal:/home/.local/share/signal-cli:Z`),
and `,z` to the photos volume (`./photos:/photos:ro,z`).

**Still stuck?** [Open an issue](https://github.com/jodab/nejomibot/issues).

## Where the image comes from

Each release's images are built and pushed by the repository's own release
workflow on GitHub, from the release's commit, with signed build provenance
(since 0.94.0). With the [GitHub CLI](https://cli.github.com/), logged in,
you can check that an image is one of them:

```sh
gh attestation verify oci://docker.io/jodab/nejomibot:latest --repo jodab/nejomibot
```

It shows the workflow that built the image, and from which commit.

## Learn more

- [The README](https://github.com/jodab/nejomibot#readme): every command,
  the allowed list, timers, specials, languages and settings
- [The health checks](https://github.com/jodab/nejomibot#health-checks)
- [Running the bot with Podman Quadlets](https://github.com/jodab/nejomibot#podman-quadlets)
- [The changelog](https://github.com/jodab/nejomibot/blob/main/CHANGELOG.md)
