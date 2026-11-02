#!/bin/bash
# Starts the desktop stack. Every service runs in its own restart loop and logs
# why it stopped: the container itself never exits on a service failure, since
# pi3 runs it with --rm and an exit would take the logs with it.
set -uo pipefail

log() { echo "browserbox: $*" >&2; }

# keep NAME CMD...: run CMD forever; on exit log the code and the last stderr lines.
keep() {
  local name=$1 err=/tmp/$1.err
  shift
  while true; do
    "$@" 2>"$err"
    log "$name exited with code $?, restarting in 2s; last stderr:"
    tail -n 15 "$err" | sed "s/^/  [$name] /" >&2
    sleep 2
  done
}

log "starting as $(id -un) ($(id -u):$(id -g)), data volume: $(stat -c '%u:%g %a' /home/sandbox/data 2>&1)"
DATA=/home/sandbox/data
if ! touch "$DATA/.writable" 2>/dev/null; then
  log "WARNING: $DATA is not writable; logins and the password will NOT survive a restart"
  DATA=/tmp/data
fi
PROFILE=$DATA/chromium
mkdir -p "$PROFILE" /home/sandbox/Uploads /home/sandbox/Downloads

# One password for the desktop, the API and CDP; generated once, kept in the volume.
if [ ! -s "$DATA/password" ]; then
  (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(18))' > "$DATA/password")
fi
export BBX_USER=sandbox
BBX_HASH=$(caddy hash-password --plaintext "$(cat "$DATA/password")")
export BBX_HASH
log "login user '$BBX_USER', password: $(cat "$DATA/password")"

SCREEN=${SCREEN:-1280x800x24}
W=${SCREEN%%x*}; H=${SCREEN#*x}; WIN_SIZE="$W,${H%%x*}"
keep xvfb Xvfb "$DISPLAY" -screen 0 "$SCREEN" -nolisten tcp -dpi 96 &
for _ in $(seq 100); do [ -e "/tmp/.X11-unix/X${DISPLAY#:}" ] && break; sleep 0.1; done
keep openbox openbox &
# VNC only on localhost: reachable through websockify, behind Caddy's basic auth.
keep x11vnc x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -forever -shared -nopw -quiet -noxdamage &
keep websockify websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 &
keep control python3 /opt/browserbox/control.py &
keep caddy caddy run --config /opt/browserbox/Caddyfile --adapter caddyfile &

chrome() {
  rm -f "$PROFILE"/Singleton*
  chromium \
    --user-data-dir="$PROFILE" \
    --no-sandbox --disable-dev-shm-usage --test-type \
    --no-first-run --no-default-browser-check --password-store=basic \
    --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --remote-allow-origins='*' \
    --start-maximized --window-position=0,0 --window-size="$WIN_SIZE" --lang=en-US
}
keep chromium chrome &

trap 'kill $(jobs -p) 2>/dev/null; exit 0' TERM INT
wait
