"""Agent API for the browserbox desktop: screenshots, mouse/keyboard, file drop.

Listens on 127.0.0.1 only; Caddy puts it behind basic auth at /api/*.

  GET    /healthz            200 when X and Chromium (CDP) answer
  GET    /api/screenshot     PNG of the whole screen (with cursor)
  POST   /api/action         JSON, one of:
           {"action": "click", "x": 10, "y": 20, "button": "left|right|middle", "count": 1}
           {"action": "move", "x": 10, "y": 20}
           {"action": "drag", "x": 10, "y": 20, "to_x": 30, "to_y": 40}
           {"action": "scroll", "x": 10, "y": 20, "direction": "up|down|left|right", "amount": 3}
           {"action": "type", "text": "hello"}
           {"action": "key", "keys": "ctrl+l"}      (xdotool names, space-separated sequence)
           {"action": "cursor"}
  GET    /api/files          list of files in ~/Uploads (what the browser can pick)
  PUT    /api/files/<name>   upload a file to ~/Uploads/<name> (needs Content-Length)
  DELETE /api/files/<name>   remove it
"""

import json
import os
import subprocess
import tempfile
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

UPLOADS = os.path.expanduser("~/Uploads")
BUTTONS = {"left": "1", "middle": "2", "right": "3"}
SCROLL = {"up": "4", "down": "5", "left": "6", "right": "7"}


class BadRequest(Exception):
    pass


def xdotool(*args):
    r = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"xdotool exited {r.returncode}")
    return r.stdout.strip()


def coord(body, kx="x", ky="y"):
    try:
        return str(int(body[kx])), str(int(body[ky]))
    except (KeyError, TypeError, ValueError):
        raise BadRequest(f"`{kx}` and `{ky}` must be integers")


def act(body):
    a = body.get("action")
    if a == "click":
        x, y = coord(body)
        button = BUTTONS.get(body.get("button", "left"))
        if not button:
            raise BadRequest("button must be left, middle or right")
        count = str(max(1, min(3, int(body.get("count", 1)))))
        xdotool("mousemove", "--sync", x, y, "click", "--repeat", count, "--delay", "80", button)
    elif a == "move":
        xdotool("mousemove", "--sync", *coord(body))
    elif a == "drag":
        xdotool("mousemove", "--sync", *coord(body), "mousedown", "1",
                "mousemove", "--sync", *coord(body, "to_x", "to_y"), "mouseup", "1")
    elif a == "scroll":
        button = SCROLL.get(body.get("direction", "down"))
        if not button:
            raise BadRequest("direction must be up, down, left or right")
        amount = str(max(1, min(50, int(body.get("amount", 3)))))
        xdotool("mousemove", "--sync", *coord(body), "click", "--repeat", amount, button)
    elif a == "type":
        text = body.get("text")
        if not isinstance(text, str):
            raise BadRequest("`text` must be a string")
        xdotool("type", "--delay", "12", "--", text)
    elif a == "key":
        keys = body.get("keys")
        if not isinstance(keys, str) or not keys.strip():
            raise BadRequest("`keys` must be a non-empty string, e.g. ctrl+l")
        xdotool("key", "--", *keys.split())
    elif a != "cursor":
        raise BadRequest("unknown action")
    loc = dict(kv.split(":") for kv in xdotool("getmouselocation").split()[:2])
    return {"ok": True, "cursor": {"x": int(loc["x"]), "y": int(loc["y"])}}


def screenshot():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.png")
        subprocess.run(["scrot", "--pointer", "--overwrite", path], check=True, timeout=30)
        with open(path, "rb") as f:
            return f.read()


def upload_path(raw):
    name = os.path.basename(unquote(raw))
    if not name or name.startswith("."):
        raise BadRequest("bad file name")
    return os.path.join(UPLOADS, name)


def healthy():
    try:
        xdotool("getdisplaygeometry")
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3):
            return True
    except Exception:
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_safely(self, fn):
        try:
            fn()
        except BadRequest as e:
            self.send(400, {"error": str(e)})
        except Exception as e:  # report, keep serving
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        def run():
            if self.path == "/healthz":
                ok = healthy()
                self.send(200 if ok else 503, {"ok": ok})
            elif self.path == "/api/screenshot":
                self.send(200, screenshot(), "image/png")
            elif self.path == "/api/files":
                files = sorted(n for n in os.listdir(UPLOADS) if not n.endswith(".part"))
                self.send(200, [{"name": n, "path": os.path.join(UPLOADS, n),
                                 "size": os.path.getsize(os.path.join(UPLOADS, n))} for n in files])
            else:
                self.send(404, {"error": "not found"})
        self.handle_safely(run)

    def do_POST(self):
        def run():
            if self.path != "/api/action":
                return self.send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise BadRequest("body must be JSON")
            if not isinstance(body, dict):
                raise BadRequest("body must be a JSON object")
            self.send(200, act(body))
        self.handle_safely(run)

    def do_PUT(self):
        def run():
            if not self.path.startswith("/api/files/"):
                return self.send(404, {"error": "not found"})
            path = upload_path(self.path[len("/api/files/"):])
            length = self.headers.get("Content-Length")
            if length is None:
                raise BadRequest("Content-Length required (curl -T sends it)")
            left = int(length)
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        raise BadRequest("upload cut short")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(tmp, path)
            self.send(201, {"path": path, "size": os.path.getsize(path)})
        self.handle_safely(run)

    def do_DELETE(self):
        def run():
            if not self.path.startswith("/api/files/"):
                return self.send(404, {"error": "not found"})
            path = upload_path(self.path[len("/api/files/"):])
            if not os.path.exists(path):
                return self.send(404, {"error": "no such file"})
            os.remove(path)
            self.send(200, {"ok": True})
        self.handle_safely(run)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    os.makedirs(UPLOADS, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", 8081), Handler).serve_forever()
