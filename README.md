# pi3-browse

A Chromium desktop in a container on the homelab, for "computer use": the owner
logs in to sites (YouTube, …) through the web desktop, then Claude sessions in
pi3 drive the same logged-in browser.

- **Owner:** open the app URL (`hlab status pi3-browse`), user `sandbox`, the
  password from the logs (`pi3-browse: login user 'sandbox', password: …`).
  It is generated on first start and kept in the `data` volume with the
  Chromium profile, so logins and the password survive redeploys.
- **Agents:** `pi3-browse` (tools/pi3-browse, linked into `~/.local/bin`) finds the URL and
  password through `hlab` by itself.

Only reachable on the tailnet (`expose: tailnet`; pi3-deploy cannot do tailscale serve). Everything except `/healthz`
is behind basic auth.

## What runs inside

Xvfb (1280x800) + openbox + Chromium as uid 1000, no capabilities. Chromium uses
`--no-sandbox` because pi3-deploy grants no capabilities; the container is the
sandbox. Caddy on :8080 routes:

| path | what |
|---|---|
| `/` → `/vnc.html` | noVNC desktop (x11vnc + websockify) |
| `/api/*` | control API (`rootfs/opt/pi3-browse/control.py`): screenshot, click/type/key/scroll/drag, file upload into `~/Uploads` |
| `/json*`, `/devtools/*` | Chrome DevTools Protocol |
| `/healthz` | 200 once X and Chromium answer (no auth) |

## Driving it as an agent

Pixel level (Claude computer-use style: look at the screenshot, act, repeat):

    pi3-browse shot                       # → /tmp/pi3-browse-shot.png, then Read it
    pi3-browse click 640 400
    pi3-browse type "hello"; pi3-browse key Return
    pi3-browse open https://studio.youtube.com

DOM level with Playwright over CDP (same logged-in profile):

```js
const { wsEndpoint, headers } = JSON.parse(execSync("pi3-browse cdp", { encoding: "utf8" }));
const browser = await chromium.connectOverCDP(wsEndpoint, { headers });
const page = browser.contexts()[0].pages()[0];
```

Files (videos to post): `pi3-browse upload ./clip.mp4` copies it to
`/home/sandbox/Uploads/clip.mp4` inside the box. Give that path to a file
input with raw CDP (`DOM.setFileInputFiles` with `files: [path]`), or type it in
the file dialog (`ctrl+l`, path, Enter). Uploads are not in the volume and go
away on redeploy; `pi3-browse rm NAME` frees space sooner.

## Deploy

Push to main → the Image workflow builds `ghcr.io/ut001ms/pi3-browse:sha-<commit>`
(the package must be public, pi3-deploy has no GHCR credential), then
`hlab deploy . --ref HEAD --message "…"`.
