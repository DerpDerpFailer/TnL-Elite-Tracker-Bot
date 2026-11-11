#!/usr/bin/env bash
# Restore the bot's data folder (elite.json, elite.json.bak, maps/) on Unraid,
# from an Appdata Backup archive (default: the latest one) or from a plain folder.
# The target becomes an exact copy of the source (files missing from the source
# are removed); the current data is snapshotted first.
#
# Dry-run by default: nothing is changed unless --apply is given.
# Runs on the Unraid host as root; from the Mac, without installing anything:
#
#   ssh root@192.168.1.240 'bash -s -- [options]' < scripts/restore-tnl-elite-data-unraid.sh
#
# Options:
#   --backup NAME      Appdata Backup run to restore from (e.g. ab_20261115_040001)
#   --from-dir DIR     restore from a folder holding elite.json instead
#                      (rollback snapshot, rescue backup...)
#   --apply            really restore (stop bot, snapshot, copy, chown, verify, start)
#   --data-dir DIR     target folder      (default: /mnt/user/appdata/tnl-elite-bot/data)
#   --container NAME   bot container      (default: tnl-elite-bot)
#   --image IMAGE      image used to validate the JSON (default: the container's image)
#   --backup-root DIR  Appdata Backup root (default: /mnt/user/documents/backup-appdata)
#   -h, --help         show this help
set -euo pipefail

DATA_DIR="/mnt/user/appdata/tnl-elite-bot/data"
CONTAINER="tnl-elite-bot"
BACKUP_ROOT="/mnt/user/documents/backup-appdata"
BACKUP=""
FROM_DIR=""
IMAGE=""
APPLY=0
OWNER="1000:1000"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }
usage() {
  cat <<'EOF'
Usage: ssh root@192.168.1.240 'bash -s -- [options]' < scripts/restore-tnl-elite-data-unraid.sh
  --backup NAME | --from-dir DIR   source (default: latest Appdata Backup run)
  --apply                          really restore (default: dry-run)
  --data-dir DIR  --container NAME  --image IMAGE  --backup-root DIR
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --backup)      BACKUP="${2:?--backup needs a value}"; shift 2 ;;
    --from-dir)    FROM_DIR="${2:?--from-dir needs a value}"; shift 2 ;;
    --data-dir)    DATA_DIR="${2:?--data-dir needs a value}"; shift 2 ;;
    --container)   CONTAINER="${2:?--container needs a value}"; shift 2 ;;
    --image)       IMAGE="${2:?--image needs a value}"; shift 2 ;;
    --backup-root) BACKUP_ROOT="${2:?--backup-root needs a value}"; shift 2 ;;
    --apply)       APPLY=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             die "unknown option: $1 (see --help)" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "must run as root on the Unraid host"
[ -z "$BACKUP" ] || [ -z "$FROM_DIR" ] || die "--backup and --from-dir are mutually exclusive"
command -v docker >/dev/null || die "docker not found"
command -v rsync >/dev/null || die "rsync not found"

WORK="$(mktemp -d /tmp/tnl-elite-restore.XXXXXX)"
STOPPED=0
SNAPSHOT=""
on_exit() {
  local rc=$?
  rm -rf "$WORK"
  if [ "$rc" -ne 0 ] && [ "$STOPPED" -eq 1 ]; then
    log "FAILED after stopping $CONTAINER: it is left stopped."
    [ -z "$SNAPSHOT" ] || log "Data as it was before the restore: $SNAPSHOT"
    log "Check $DATA_DIR, then: docker start $CONTAINER"
  fi
}
trap on_exit EXIT

# ── Resolve the source folder ────────────────────────────────────────────────
if [ -n "$FROM_DIR" ]; then
  [ -d "$FROM_DIR" ] || die "folder not found: $FROM_DIR"
  SRC="$(cd "$FROM_DIR" && pwd)"
  log "Source: folder $SRC"
else
  if [ -z "$BACKUP" ]; then
    # Latest run that actually contains an archive for this container.
    # ab_YYYYMMDD_HHMMSS sorts chronologically; the glob expands in ascending order.
    for run in "$BACKUP_ROOT"/ab_*; do
      [ -f "$run/$CONTAINER.tar.gz" ] && BACKUP="$(basename "$run")"
    done
    [ -n "$BACKUP" ] || die "no Appdata Backup run under $BACKUP_ROOT contains $CONTAINER.tar.gz"
  fi
  ARCHIVE="$BACKUP_ROOT/$BACKUP/$CONTAINER.tar.gz"
  [ -f "$ARCHIVE" ] || die "archive not found: $ARCHIVE"
  log "Source: archive $ARCHIVE"
  tar -xzf "$ARCHIVE" -C "$WORK"
  # The archive layout depends on the plugin: locate elite.json wherever it is.
  mapfile -t dirs < <(find "$WORK" -type f -name elite.json -printf '%h\n' | sort -u)
  [ "${#dirs[@]}" -gt 0 ] || die "no elite.json in $ARCHIVE"
  [ "${#dirs[@]}" -eq 1 ] || die "elite.json found in several folders of the archive: ${dirs[*]}"
  SRC="${dirs[0]}"
  log "Data found in the archive at ${SRC#"$WORK"/}"
fi
[ -f "$SRC/elite.json" ] || die "no elite.json in $SRC"

# ── Validate the JSON with the bot's own image (Unraid has no python) ───────
if [ -z "$IMAGE" ]; then
  IMAGE="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null)" \
    || die "container $CONTAINER not found; pass --image to validate the JSON"
fi
# The file is passed on stdin: it is 0600 and may be owned by another UID.
summary="$(docker run --rm -i --network none --entrypoint python "$IMAGE" \
  -c '
import json, sys
from bot.constants import SCHEMA_VERSION
try:
    d = json.load(sys.stdin)
except ValueError as e:
    sys.exit(f"invalid JSON: {e}")
if not isinstance(d, dict) or not isinstance(d.get("version"), int):
    sys.exit("a JSON object with an integer version field is expected")
version, guilds, zones = d["version"], len(d.get("guilds", {})), len(d.get("zones", {}))
if version > SCHEMA_VERSION:
    sys.exit(f"schema {version} is newer than this image supports ({SCHEMA_VERSION})")
print(f"schema {version}, {guilds} guild(s), {zones} zone(s)")' < "$SRC/elite.json")" \
  || die "elite.json is not a valid bot state"
log "elite.json valid: $summary"

# ── Plan ─────────────────────────────────────────────────────────────────────
mkdir -p "$WORK/empty"
target="$DATA_DIR"; [ -d "$target" ] || target="$WORK/empty"
plan="$(rsync -rlpt --delete --checksum --dry-run --itemize-changes "$SRC"/ "$target"/ | grep -v '^\.d' || true)"
changes="$(printf '%s' "$plan" | grep -c . || true)"
[ -z "$plan" ] || printf '%s\n' "$plan" | sed 's/^/  /' >&2

if [ "$APPLY" -eq 0 ]; then
  log "Dry-run: nothing changed ($changes change(s) planned). Re-run with --apply to restore."
  exit 0
fi
[ "$changes" -gt 0 ] || { log "Nothing to restore: target already matches the source."; exit 0; }

# ── Apply ────────────────────────────────────────────────────────────────────
was_running="$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo false)"
if [ "$was_running" = "true" ]; then
  log "Stopping $CONTAINER"
  docker stop "$CONTAINER" >/dev/null
  STOPPED=1
fi

mkdir -p "$DATA_DIR"
SNAPSHOT="$DATA_DIR.before-restore-$(date '+%Y%m%d-%H%M%S')"
cp -a "$DATA_DIR" "$SNAPSHOT"
log "Current data saved to $SNAPSHOT"

rsync -rlpt --delete --checksum "$SRC"/ "$DATA_DIR"/
chown -R "$OWNER" "$DATA_DIR"
leftover="$(rsync -rlpt --delete --checksum --dry-run --itemize-changes "$SRC"/ "$DATA_DIR"/ | grep -v '^\.d' || true)"
[ -z "$leftover" ] || die "target differs from the source after the copy: $leftover"
log "Restored $changes change(s), owner $OWNER, checksums OK"

if [ "$was_running" = "true" ]; then
  log "Starting $CONTAINER"
  docker start "$CONTAINER" >/dev/null
  STOPPED=0
  sleep 5
  docker logs --tail 20 "$CONTAINER" 2>&1 | sed 's/\x1b\[[0-9;]*m//g' >&2
else
  log "$CONTAINER was not running: left stopped"
fi
log "Done. Rollback: same command with --from-dir $SNAPSHOT --apply"
