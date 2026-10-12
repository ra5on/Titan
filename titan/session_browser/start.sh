#!/bin/sh
set -eu
umask 077
mkdir -p "$HOME/profile" "$HOME/Downloads"
Xvfb :0 -screen 0 "${WIDTH:-1440}x${HEIGHT:-900}x24" -nolisten tcp &
for attempt in $(seq 1 100); do
    if xrandr >/dev/null 2>&1; then break; fi
    sleep 0.1
done
# A window manager keeps popups and new browser windows inside the same session.
openbox &
# Chromium's own sandbox remains enabled. Never mount the Docker socket here.
chromium --no-first-run --no-default-browser-check --disable-dev-shm-usage \
    --user-data-dir="$HOME/profile" --start-maximized --app="$APP_URL" &
browser_pid=$!
sleep 2
kill -0 "$browser_pid"
x11vnc -display :0 -forever -shared -rfbport 5900 -rfbauth /run/titan-vnc -noxdamage &
wait "$browser_pid"
