# TnL Elite Tracker Bot

A multi-server-installable Discord bot that tracks Elite PvP boss respawn
timers for **Throne and Liberty**. Members log kills and no-shows, the bot
computes the next expected spawn time per zone, keeps a live status embed up
to date, and posts a per-sub-zone scouting alert (with the zone's map
attached) that updates in place as the boss is found and killed. The boss
timers are one shared, mutualized state: install the bot on several
communities' servers and a kill/scout/found report on any one of them is
instantly reflected everywhere else too — see
[Multi-server installs](#multi-server-installs).

State is a single JSON file (`/data/elite.json`), written atomically with a
`.bak` copy kept on every write — there is no database.

## Contents

- [How it works](#how-it-works)
- [Multi-server installs](#multi-server-installs)
- [Discord Developer Portal setup](#discord-developer-portal-setup)
- [Invite URL](#invite-url)
- [Local development](#local-development)
- [Running tests](#running-tests)
- [Pre-configured zones, sub-zones and maps](#pre-configured-zones-sub-zones-and-maps)
- [Fallback timer sync](#fallback-timer-sync)
- [Deploying with Portainer](#deploying-with-portainer)
- [Updating the bot](#updating-the-bot)
- [Command reference](#command-reference)
- [Data file layout](#data-file-layout)

## How it works

- Each zone has a configurable cooldown. After a kill is logged, the boss is
  expected to respawn at exactly `cooldown` after the kill, at one of several
  possible **sub-zones** within the region.
- A single embed message (the "perpetual message") in a configured channel
  shows live status for every zone, using Discord's native `<t:...>`
  timestamps so each member sees times in their own timezone.
- A background task checks every 30 seconds whether a pre-alert is due, or
  whether the spawn time has been reached, for any zone — but only the
  pre-alert ever posts a *new* message. Reaching the spawn time just silently
  edits that same scouting message in place, to keep the number of embeds
  down to one alert cycle per spawn (see below).
- The pre-alert gives every sub-zone its own row with two buttons: **"🔍
  `<sub-zone>`"** toggles that member in/out of the sub-zone's scout list
  (the embed updates live for everyone, plus that sub-zone's own map image
  sent ephemerally if one was uploaded), and a plain 📍 button (icon only)
  announces the boss was located there — it disables 🔍/📍 for the whole
  zone (across every message it spans) since there's no more need to keep
  scouting once it's found, marks the shared embed's title "... Scouting -
  Done" with a bold "Elite found at `<sub-zone>`" note, and posts a new
  pinged announcement embed (with that sub-zone's map attached if one was
  uploaded) that carries two buttons of its own: 💀 to report the kill right
  there without scrolling back to the scouting message, and 🔄 to undo the
  found report if it was a mistake — that re-enables 🔍/📍 on the scouting
  message(s) and deletes the announcement.
- Once the spawn time is reached, that same scouting message is edited
  in-place (title → "... Scouting — Spawn Due", no new message, no ping) to
  add a third button per row: a plain 💀 **"Elite killed"** button (icon
  only, to keep the row compact) — also present on the Elite Found
  announcement, so the kill can be reported from either place. Scouting/Elite
  Found stay active after spawn time (the boss may not pop exactly on
  schedule), but clicking 💀 — on whichever sub-zone row it actually died in
  — closes out *that zone's* cycle only: every scouting message and the
  Elite Found announcement for that zone are deleted, and a new "💀 Boss
  killed" embed is posted in their place with the zone, sub-zone, kill time
  and who reported it. It's the button equivalent of `/elite-killed`.
- Discord caps a message at 5 button rows, so zones with more than 5
  sub-zones get extra messages for the rest of the buttons — all of them
  stay in sync with the same shared embed on the first message, and all get
  the "Elite killed" button added at spawn time too.
- All buttons are persistent — they keep working on old alert messages even
  after a bot restart.
- Every ephemeral reply (command confirmations, errors, button feedback) is
  only visible to the person who triggered it and auto-deletes itself about
  12 seconds later, so it doesn't linger for them to dismiss by hand.
- All game-side values (cooldowns, zones, sub-zones, map images, timezone)
  are configured through `/elite-config` — the game is patched weekly, so
  nothing here should require touching code or redeploying for a balance
  change. Channel/alert-role/admin-role are configured the same way but are
  per-server (see below).

## Multi-server installs

The bot can be invited to any number of Discord servers with the same
[Invite URL](#invite-url) and without a separate stack/deploy per server —
every installed server shares the exact same underlying zone/timer state
(cooldowns, current spawn times, sub-zones, maps), which is what lets a
report on one server show up on every other one instantly. Concretely:

- **Per-server settings** (`/elite-config channel`, `alert-channel`,
  `alert-role`, `admin-role`, `repost`, `show`) apply only to the server the
  command is run on — each installed server picks its own status/alert
  channel and its own role to ping, independently.
- **Shared settings** (`/elite-config cooldown`, `zone-add`/`zone-remove`,
  `subzone-add`/`subzone-remove`, `map`/`submap`, `reset-maps`, `sync-zones`,
  and the whole `/elite-config fallback ...` group) edit the one shared
  state, so they're restricted to the **owner server** — the one named by
  the `OWNER_GUILD_ID` environment variable (see below) — to keep any other
  installed server's admins from accidentally changing everyone's cooldowns
  or maps. Every other admin command (and all member-facing commands) works
  the same on every installed server.
- When the bot joins a new server, it registers slash commands there right
  away (no waiting on Discord's slower global command propagation) and seeds
  an empty per-server config — an admin just needs to run `/elite-config
  channel` (and optionally `alert-channel`/`alert-role`) to start receiving
  alerts.

If you only ever plan to run this on one server, none of this changes
anything day-to-day — just set `OWNER_GUILD_ID` to that server's ID and
everything behaves as a single-server bot.

## Discord Developer Portal setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   and click **New Application**. Name it (e.g. "TnL Elite Tracker").
2. Open the **Bot** tab:
   - Click **Reset Token** / **Copy** to get your bot token — this is the
     `DISCORD_TOKEN` value. Keep it secret; it is never committed to this
     repository.
   - **Privileged Gateway Intents**: leave all three toggles (Presence,
     Server Members, Message Content) **off**. This bot only uses slash
     commands and never reads message content, so no privileged intent is
     required.
3. Open the **OAuth2 → General** tab if you need the **Application (Client)
   ID** for the invite URL below.
4. You will also need your **owner server's Guild ID** (see
   [Multi-server installs](#multi-server-installs)): enable Developer Mode
   in Discord (User Settings → Advanced), then right-click your server icon
   → **Copy Server ID**. This is the `OWNER_GUILD_ID` value.

## Invite URL

Build the invite URL with the **`bot`** and **`applications.commands`**
scopes and the minimal permission set the bot actually needs: view the
channel, send messages, embed links (required for all the embeds), attach
files (map images), mention everyone/roles (required to ping the configured
alert role, which is typically not a self-mentionable role), and **read
message history** — required for `fetch_message`, which the bot uses to find
its own perpetual status message by ID and edit it (including right after a
restart, to find a message posted before the bot came back up). Without it,
the bot silently fails to edit the perpetual message and only logs a
"missing permissions" warning.

That permission set is the integer **`248832`**. Replace `YOUR_CLIENT_ID`
below with your application's Client ID:

```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot+applications.commands&permissions=248832
```

If the bot is already in your server with the old permission set, you don't
need to kick and re-invite it: open the URL above and click **Authorize**
again — Discord updates the existing bot role's permissions in place. You can
also add it manually from **Server Settings → Roles** → the bot's
auto-created role → enable **Read Message History**.

Open that URL, pick your server, and authorize it.

## Local development

Only useful for testing outside of Portainer. Requires Python 3.12+.

```bash
cp .env.example .env
# edit .env and fill in DISCORD_TOKEN and OWNER_GUILD_ID

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p data  # local stand-in for the /data volume
python -m bot.main
```

By default the bot reads/writes `/data/elite.json`, which only exists inside
the container. For a genuinely local run outside Docker, either create
`/data` locally (requires permissions) or run via `docker compose` as
described below — that's the supported path for anything beyond a quick
syntax check.

## Running tests

The test suite covers the pure logic (cooldown/duration/date parsing, kill/
no-show/undo/sub-zone domain logic, the JSON schema migrations, embed/button
construction) and the interactive scouting/found/kill/undo button flows
using lightweight fake Discord objects (`tests/fakes.py`) — no live bot
token or gateway connection needed.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m pytest
```

Requires Python 3.12+ (same as the bot itself). A GitHub Actions workflow
(`.github/workflows/tests.yml`) runs the same suite on every push/PR to
`main`.

## Pre-configured zones, sub-zones and maps

The `images/` folder at the repo root (`Zone.png` / `Zone - Sub-zone.png`) is
bundled straight into the Docker image (see the `Dockerfile`'s
`COPY images ./images`) and matched to zones/sub-zones via the table in
`bot/default_maps.py`. On every startup, the bot copies any of these bundled
images into `/data/maps` that isn't already there — so a brand new install
(or a fresh `/data` volume on a different server) comes up fully
pre-configured with every default zone, sub-zone and map, with nothing to
run by hand.

It only ever fills in what's *missing*: a map already in `/data/maps` (e.g.
one you replaced with `/elite-config map`/`submap`) is never overwritten by
the bundled default. Those two commands remain the way to add a map for a
custom zone/sub-zone, or to replace a bundled one with something else. If a
zone already had a placeholder/test map uploaded before it had a bundled
default, that stale file will never get auto-replaced — use
`/elite-config reset-maps zone` to force it back to the bundled default.

To add or update a bundled default yourself, drop the image into `images/`
following the same `Zone.png`/`Zone - Sub-zone.png` naming, add the matching
entry to `IMAGE_MAP` in `bot/default_maps.py`, and commit both.

Use `/elite-config preview-zone`/`preview-map` (see below) to visually verify
maps landed correctly after a deploy.

## Fallback timer sync

**Off by default.** When enabled, and a zone's spawn time is missing or
overdue by a configurable threshold, the bot checks
[mmopartybuilder.eu](https://mmopartybuilder.eu)'s community boss-timer maps
(one per PvP world) for a more recent kill, and adopts it if found — same
effect as clicking the "Elite killed" button: the zone's scouting/found
messages are closed out and a "Boss killed" summary is posted (with a
"Sub-zone: Unknown" field, since that site only tracks a zone-wide timer, not
which sub-zone specifically), just without a real Discord reporter.

This talks to an internal API of that site, not a published/documented
integration, so it's built to fail completely silently: any network error,
timeout, or unexpected response shape is caught and logged, never surfaced
to users and never blocking anything else the bot does. It's also rate-
limited to at most once every 5 minutes per zone while that zone stays
stale, so a zone nobody reports for hours doesn't hammer that site
indefinitely.

| Command | Description |
|---|---|
| `/elite-config fallback enabled enabled` | Turn fallback sync on/off. |
| `/elite-config fallback server server` | Which PvP world to check: Sacred, Sophia, Indomitable, Usurper, or Fearless. |
| `/elite-config fallback threshold minutes` | How overdue/missing a zone's timer must be before it's checked (default 5). |
| `/elite-config fallback sync zone` | Force an immediate check for one zone, regardless of the settings above. |
| `/elite-config fallback sync-all` | Force an immediate check for every zone. |

### Found-watch

**Off by default.** While fallback sync only ever reports a zone-wide kill
(no sub-zone), found-watch instead polls mmopartybuilder.eu's *live scouting
board* for the same sub-zone-level "found here" report a member would submit
by clicking 📍 — so if enabled, the bot can auto-detect and announce the
Elite's location, not just its death. Polling starts the moment a zone's
spawn window opens and stops as soon as it's found (by anyone, on Discord or
the site) or the cycle moves on.

It runs fast (every ~20s) for a configurable number of attempts, since
that's when someone's most likely to already be actively scouting; once
that budget is used up it backs off to a much slower interval, since quiet
hours (e.g. early morning) can otherwise mean nobody reports for a long time
and there's no point hammering the endpoint waiting for that.

| Command | Description |
|---|---|
| `/elite-config fallback found-watch-enabled enabled` | Turn found-watch on/off. |
| `/elite-config fallback found-watch-attempts attempts` | How many fast-phase (~20s) attempts before backing off (default 10). |
| `/elite-config fallback found-watch-interval minutes` | How often it checks once the fast-phase attempts are exhausted (default 15). |

## Deploying with Portainer

The bot is deployed as a **Portainer Stack of type "Repository"**, pointed at
this GitHub repository, so redeploys are a matter of pulling the latest
commit rather than pushing images by hand.

### 1. Create a GitHub Personal Access Token (read-only)

Since this repository is private, Portainer needs a token to clone it:

1. On GitHub, go to **Settings → Developer settings → Personal access
   tokens → Fine-grained tokens → Generate new token**.
2. **Repository access**: select "Only select repositories" and choose
   `TnL-Elite-Tracker-Bot`.
3. **Permissions**: under "Repository permissions", set **Contents** to
   **Read-only**. Nothing else is required.
4. Generate the token and copy it immediately (it won't be shown again).

### 2. Create the Stack in Portainer

1. In Portainer, go to **Stacks → Add stack**.
2. **Build method**: select **Repository**.
3. **Repository URL**: `https://github.com/<your-account>/TnL-Elite-Tracker-Bot`
4. **Repository reference**: `refs/heads/main`
5. **Compose path**: `docker-compose.yml`
6. **Authentication**: enable it, and provide:
   - **Username**: your GitHub username (or any placeholder — fine-grained
     tokens authenticate by token, but GitHub still expects a username field)
   - **Personal Access Token**: the token created above
7. **Environment variables**: add
   - `DISCORD_TOKEN` = your bot token
   - `OWNER_GUILD_ID` = your owner server's guild ID (see
     [Multi-server installs](#multi-server-installs))

   These are stack-level secrets in Portainer, **not** committed anywhere in
   this repo — `docker-compose.yml` only references `${DISCORD_TOKEN}` and
   `${OWNER_GUILD_ID}`.
8. (Optional, recommended) Enable **GitOps updates** and set a **webhook** or
   polling interval so the stack automatically redeploys whenever `main` is
   pushed. If you skip this, use the manual "Pull and redeploy" button
   described below.
9. Click **Deploy the stack**.

Portainer will clone the repo, build the image from the `Dockerfile`, and
start the `elite-tracker-bot` service with the named volume `elite-data`
mounted at `/data` (a named volume is used deliberately — a relative bind
mount doesn't work reliably with Portainer's git-based stacks, since the
repo is checked out into an ephemeral location).

## Updating the bot

- **Manual**: after pushing to `main`, open the stack in Portainer and click
  **Pull and redeploy** — this re-clones the repo at the latest commit,
  rebuilds the image, and restarts the container. Data in `/data` is
  untouched since it lives in the named volume, not the image.
- **Automatic (optional)**: if you enabled GitOps/webhook updates when
  creating the stack, Portainer redeploys automatically on every push to
  `main` — no manual step needed.

## Command reference

### Member commands

| Command | Description |
|---|---|
| `/elite-killed zone heure` | Report a kill. `zone` autocompletes; `heure` is optional (`HH:MM` for today, or `DD/MM HH:MM`), defaults to now. |
| `/elite-noshow zone` | Report that the boss did not spawn at the expected time; pushes the timer back by one full cooldown. |
| `/elite-undo zone` | Undo the last kill/no-show entry for that zone. |
| `/elite-status` | Ephemeral table of every zone: last kill, next spawn time, who reported it. |
| `/elite-stats zone` | Up to the last 10 observed kill-to-kill intervals and their average, flagged if it drifts >15 min from the configured cooldown. |
| `/elite-zones` | Nested list of every tracked zone and its sub-zones. |

Examples:

```
/elite-killed zone:Laslan
/elite-killed zone:Nix heure:21:45
/elite-killed zone:Talandre heure:14/07 09:10
/elite-noshow zone:Stonegard
/elite-undo zone:Talandre
/elite-status
/elite-stats zone:Nix
/elite-zones
```

### Admin commands (`/elite-config ...`)

Requires the **Manage Server** permission, or the role configured via
`admin-role` below. Discord server admins can additionally grant/restrict
individual subcommands per-role from **Server Settings → Integrations** for
finer-grained control.

Commands marked **🔒 owner only** below edit state shared by every installed
server and only work on the server named by `OWNER_GUILD_ID` — see
[Multi-server installs](#multi-server-installs). Everything else applies
only to the server the command is run on.

| Subcommand | Description |
|---|---|
| `/elite-config cooldown zone duree` 🔒 | Set a zone's cooldown, e.g. `4h`, `5h30`, `90m`. |
| `/elite-config channel canal` | Set this server's channel for the perpetual status embed. |
| `/elite-config alert-channel canal` | Set a separate channel for this server's spawn alerts (pre-alert + spawn-time); omit to send alerts in the status channel instead. |
| `/elite-config alert-role role` | Role pinged in this server's alerts; omit to clear (no ping). |
| `/elite-config admin-role role` | Role allowed to use `/elite-config` on this server, in addition to Manage Server; omit to clear. |
| `/elite-config alert-offset minutes` 🔒 | Pre-alert delay before the spawn time (default 15). |
| `/elite-config timezone tz` 🔒 | IANA timezone used to interpret manual kill times, e.g. `Europe/Paris`. |
| `/elite-config map zone image` 🔒 | Upload/replace a zone's region-level map (PNG/JPG), attached to alerts. |
| `/elite-config zone-add nom cooldown` 🔒 | Add a new zone. |
| `/elite-config sync-zones` 🔒 | Add any built-in default zone (Laslan/Stonegard/Talandre/Nix + dungeons, with their sub-zones) that isn't already tracked. Only adds missing zones — never touches ones that already exist, even if their cooldown differs from the default. Use this after an update adds new default zones/sub-zones to the code, since the seed only runs on a brand-new `/data/elite.json`. |
| `/elite-config zone-remove zone` 🔒 | Remove a zone, its history, its sub-zones and their maps. |
| `/elite-config zone-reset zone` 🔒 | Clear a zone's last kill, current spawn time and history — keeps its cooldown, map and configured sub-zones. Useful to wipe test data or fix a bad entry beyond what `/elite-undo` can revert (it only undoes one step). |
| `/elite-config subzone-add zone nom` 🔒 | Add a scouting sub-zone to a zone. |
| `/elite-config subzone-remove zone subzone` 🔒 | Remove a sub-zone (and its map) from a zone. |
| `/elite-config submap zone subzone image` 🔒 | Upload/replace the map image for one specific sub-zone, sent ephemerally to whoever clicks its "Scouting" button. |
| `/elite-config preview-zone zone` | Show every map image for a zone (its own map plus every sub-zone's), noting any that haven't been uploaded yet — handy for checking the bundled/uploaded maps landed correctly. |
| `/elite-config preview-map zone [subzone]` | Show the map image for one specific zone or sub-zone. |
| `/elite-config reset-maps zone` 🔒 | Delete a zone's map overrides (its own + every sub-zone's) and restore the bundled defaults. Use this if a stale/placeholder upload from before a zone had a bundled default is blocking it — `/elite-config map`/`submap` never get auto-replaced otherwise. |
| `/elite-config fallback enabled enabled` 🔒 | Turn the [mmopartybuilder.eu fallback timer sync](#fallback-timer-sync) on/off (off by default). |
| `/elite-config fallback server server` 🔒 | Which PvP world the fallback sync checks. |
| `/elite-config fallback threshold minutes` 🔒 | How overdue/missing a zone's timer must be before fallback sync checks it. |
| `/elite-config fallback sync zone` 🔒 | Force an immediate fallback check for one zone. |
| `/elite-config fallback sync-all` 🔒 | Force an immediate fallback check for every zone. |
| `/elite-config fallback found-watch-enabled enabled` 🔒 | Turn [found-watch](#found-watch) on/off (off by default). |
| `/elite-config fallback found-watch-attempts attempts` 🔒 | How many fast-phase attempts found-watch makes before backing off (default 10). |
| `/elite-config fallback found-watch-interval minutes` 🔒 | How often found-watch checks once its fast-phase attempts are exhausted (default 15). |
| `/elite-config repost` | Recreate this server's perpetual status message if it was deleted by accident, or force an immediate refresh. |
| `/elite-config show` | Show the full current configuration (this server's channel/roles, plus the shared offset, timezone, zones with their cooldowns and sub-zone counts) in one embed. |

Examples:

```
/elite-config cooldown zone:Talandre duree:5h30
/elite-config channel canal:#elite-timers
/elite-config alert-channel canal:#elite-alerts
/elite-config alert-role role:@Elite Hunters
/elite-config admin-role role:@Boss Timer Admin
/elite-config alert-offset minutes:10
/elite-config timezone tz:Europe/Paris
/elite-config map zone:Nix image:nix-map.png
/elite-config zone-add nom:Aldheim cooldown:5h
/elite-config zone-remove zone:Aldheim
/elite-config sync-zones
/elite-config zone-reset zone:Laslan
/elite-config subzone-add zone:Nix nom:Frostbite Ridge
/elite-config subzone-remove zone:Nix subzone:Frostbite Ridge
/elite-config submap zone:Laslan subzone:Urstella Fields image:urstella-fields.png
/elite-config preview-zone zone:Nix
/elite-config preview-map zone:Laslan subzone:Urstella Fields
/elite-config reset-maps zone:Nix
/elite-config fallback enabled enabled:True
/elite-config fallback server server:Sacred
/elite-config fallback threshold minutes:5
/elite-config fallback sync zone:Nix
/elite-config fallback sync-all
/elite-config fallback found-watch-enabled enabled:True
/elite-config fallback found-watch-attempts attempts:10
/elite-config fallback found-watch-interval minutes:15
/elite-config repost
/elite-config show
```

## Data file layout

Seeded automatically on first boot if `/data/elite.json` doesn't exist, with
the seven zones the guild currently tracks:

| Zone | Default cooldown |
|---|---|
| Laslan | 4h |
| Stonegard | 4h |
| Talandre | 6h |
| Nix | 6h |
| Laslan Dungeon | 4h |
| Stonegard Dungeon | 4h |
| Talandre Dungeon | 6h |

These are community estimates and are expected to change after patches —
update them with `/elite-config cooldown`, no redeploy needed.

Each of these zones is also seeded with the region's known sub-zones (used
purely for the pre-alert's scouting buttons — kills are still logged at the
zone level, not per sub-zone): 7 for Laslan, 8 for Stonegard, 6 for Talandre,
5 for Nix, and 7–8 for each dungeon. Adjust the list later with
`/elite-config subzone-add` / `subzone-remove`.

Top-level JSON structure:

```jsonc
{
  "version": 15,
  "config": {
    // shared by every installed server — see "Multi-server installs"
    "alert_offset_minutes": 15,
    "timezone": "Europe/Paris",
    "fallback_enabled": false,
    "fallback_server": "sacred",
    "fallback_threshold_minutes": 5,
    "fallback_found_watch_enabled": false,
    "fallback_found_watch_attempts": 10,
    "fallback_found_watch_slow_interval_minutes": 15
  },
  "guilds": {
    // one entry per installed server, keyed by its guild ID
    "123456789012345678": {
      "channel_id": null,
      "alert_channel_id": null,
      "alert_role_id": null,
      "admin_role_id": null,
      "perpetual_message_id": null
    }
    // ...
  },
  "zones": {
    "laslan": {
      "display_name": "Laslan",
      "cooldown_minutes": 240,
      "last_kill_at": null,
      "last_kill_by": null,
      "last_kill_subzone": null,
      "spawn_at": null,
      "pre_alert_sent": false,
      "spawn_due_marked": false,
      "found_this_cycle": false,
      "subzones": {
        "urstella-fields": {
          "display_name": "Urstella Fields",
          "scouts": []
        }
        // ...
      },
      "scouting_messages": [],
      "found_announcement_messages": []
    }
    // ...
  },
  "history": {
    "laslan": []
    // up to 50 most recent kill/no-show events per zone
  }
}
```

`spawn_at` is the single expected respawn timestamp (`last_kill_at` +
cooldown) — there's no window around it, the boss is simply expected right
then. `last_kill_subzone` records which sub-zone the last kill happened in
(via a per-row "Elite killed" button), when known. A sub-zone's `scouts`
list holds the Discord user IDs currently scouting it for that pending
spawn; it's cleared automatically whenever a new kill or no-show
recalculates `spawn_at`, along with `found_this_cycle` (set once "Elite
Found" is clicked, so the spawn-time edit doesn't overwrite that state),
`scouting_messages` — a list of `{"guild_id", "channel_id", "message_id",
"subzone_keys"}`, one entry per scouting message sent this cycle across
*every* installed server (the first entry for a given `guild_id` holds that
server's live embed) — and `found_announcement_messages`, the same shape
minus `subzone_keys`, one entry per server that got an Elite Found
announcement. Together these are what let "Elite killed" find and delete
every message belonging to that zone's cycle, in every installed server,
regardless of which button (scouting message or Elite Found announcement,
on whichever server) it was clicked from.

Map images live alongside it in the named Docker volume: region-level maps
at `/data/maps/<zone>.png`, sub-zone maps at `/data/maps/<zone>__<subzone>.png`.
