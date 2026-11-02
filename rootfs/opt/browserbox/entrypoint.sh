#!/bin/bash
# Starts the desktop stack; exits (so systemd restarts the container) if any
# piece except Chromium dies. Chromium is restarted in place when closed.
set -euo pipefail

DATA=/home/sandbox/data
PROFILE=$DATA/chromium
mkdir -p "$PROFILE" /home/sandbox/Uploads /home/sandbox/Downloads
if ! touch "$DATA/.writable" 2>/dev/null; then
  echo "browserbox: $DATA is not writable by uid $(id -u); check the volume" >&2
  exit 1
fi

# One password for the desktop, the API and CDP; generated once, kept in the volume.
if [ ! -s "$DATA/password" ]; then
  (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(18))' > "$DATA/password")
fi
export BBX_USER=sandbox
BBX_HASH=$(caddy hash-password --plaintext "$(cat "$DATA/password")")
export BBX_HASH
echo "browserbox: login user '$BBX_USER', password: $(cat "$DATA/password")"

SCREEN=${SCREEN:-1280x800x24}
W=${SCREEN%%x*}; H=${SCREEN#*x}; WIN_SIZE="$W,${H%%x*}"
Xvfb "$DISPLAY" -screen 0 "$SCREEN" -nolisten tcp -dpi 96 &
for _ in $(seq 50); do [ -e "/tmp/.X11-unix/X${DISPLAY#:}" ] && break; sleep 0.1; done
openbox &
# VNC only on localhost: reachable through websockify, behind Caddy's basic auth.
x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -forever -shared -nopw -quiet -noxdamage &
websockify --web /usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 >/dev/null 2>&1 &
python3 /opt/browserbox/control.py &
caddy run --config /opt/browserbox/Caddyfile --adapter caddyfile &

(
  while true; do
    rm -f "$PROFILE"/Singleton*
    chromium \
      --user-data-dir="$PROFILE" \
      --no-sandbox --disable-dev-shm-usage --test-type \
      --no-first-run --no-default-browser-check --password-store=basic \
      --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --remote-allow-origins='*' \
      --start-maximized --window-position=0,0 --window-size="$WIN_SIZE" --lang=en-US \
      >/dev/null 2>&1 || true
    echo "browserbox: chromium exited, restarting"
    sleep 2
  done
) &

trap 'kill $(jobs -p) 2>/dev/null; exit 0' TERM INT
# The Chromium loop never ends, so any job ending means a service died.
wait -n || true
echo "browserbox: a service died, exiting" >&2
kill $(jobs -p) 2>/dev/null || true
exit 1
