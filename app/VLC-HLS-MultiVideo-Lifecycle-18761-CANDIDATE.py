import os
import runpy
import shutil
import json
import re
import sys
import time
import socket
import subprocess
import secrets
import hmac
import threading
import urllib.request

from pathlib import Path
from youtube_vlc_security import new_session_token
from youtube_vlc_security import load_install_token, verify_token
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
PORT = 18761
SOURCE = ROOT / "VLC-HLS-SIDX-VariableURL-CANDIDATE.py"
CACHE_NAME = "HLS-SIDX-Lifecycle18761-CANDIDATE"

SESSIONS = {}
LOCK = threading.RLock()
MAX_SESSIONS = 8
SESSION_MAX_AGE = 3600
SESSION_IDLE_SECONDS = 3600
SESSION_IDLE_NOTICE_SECONDS = 1800
CHILD_PORTS = range(18960, 18980)
HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

if not SOURCE.is_file():
    raise SystemExit("Missing verified 18751 candidate.")

TEMPLATE = SOURCE.read_text(encoding="utf-8")

# Hide FFmpeg's Windows console for every generated segment.
_ffmpeg_old = """        timeout=90
    )"""
_ffmpeg_new = """        timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )"""

if TEMPLATE.count(_ffmpeg_old) != 1:
    raise RuntimeError("Unexpected FFmpeg subprocess structure")

TEMPLATE = TEMPLATE.replace(
    _ffmpeg_old, _ffmpeg_new, 1
)

if TEMPLATE.count("PORT = 18751") != 1:
    raise SystemExit("Unexpected child port definition.")

if TEMPLATE.count(
    '"HLS-SIDX-VariableURL-CACHE-CANDIDATE"'
) != 1:
    raise SystemExit("Unexpected child cache definition.")

def video_id_from_url(url):
    if len(url) > 2048:
        raise ValueError("URL too long")

    parsed = urlsplit(url)

    if parsed.scheme != "https":
        raise ValueError("HTTPS required")

    if parsed.hostname not in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
    }:
        raise ValueError("Unsupported YouTube host")

    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/")
    else:
        video_id = parse_qs(parsed.query).get("v", [""])[0]

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Invalid video ID")

    return video_id


def port_available(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def child_healthy(session):
    proc = session["proc"]

    if proc.poll() is not None:
        return False

    try:
        with urllib.request.urlopen(
            session["playlist"], timeout=3
        ) as response:
            return response.status == 200
    except Exception:
        return False


def stop_child(session):
    proc = session["proc"]

    if proc.poll() is None:
        proc.terminate()

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill.exe", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=HIDE
            )

    session["log_handle"].close()



def add_child_activity_tracking(code):
    def change(old, new, label):
        nonlocal code
        if code.count(old) != 1:
            raise RuntimeError(
                "Child patch %s failed: %d matches"
                % (label, code.count(old))
            )
        code = code.replace(old, new, 1)

    change(
        "import importlib.util",
        "import importlib.util\nimport json",
        "JSON import"
    )

    change(
        "class Handler(BaseHTTPRequestHandler):",
        """ACTIVITY_LOCK = threading.Lock()
LAST_SEGMENT_REQUEST = 0.0
ACTIVE_REQUESTS = 0


class Handler(BaseHTTPRequestHandler):""",
        "activity state"
    )

    change(
        '    def handle_request(self):',
        """    def handle_request(self):
        global LAST_SEGMENT_REQUEST, ACTIVE_REQUESTS""",
        "global declaration"
    )

    change(
        '        if path == "/playlist.m3u8":',
        """        if path == "/activity":
            with ACTIVITY_LOCK:
                data = json.dumps({
                    "last_segment_request":
                        LAST_SEGMENT_REQUEST,
                    "active_requests":
                        ACTIVE_REQUESTS
                }).encode("utf-8")

            self.send_data(data, "application/json")
            return

        if path == "/playlist.m3u8":""",
        "activity endpoint"
    )

    change(
        """        try:
            segment = generate_segment(index)""",
        """        with ACTIVITY_LOCK:
            LAST_SEGMENT_REQUEST = time.time()
            ACTIVE_REQUESTS += 1

        try:
            segment = generate_segment(index)""",
        "segment request start"
    )

    change(
        '            self.send_error(500, str(error))',
        """            self.send_error(500, str(error))

        finally:
            with ACTIVITY_LOCK:
                ACTIVE_REQUESTS -= 1""",
        "segment request end"
    )

    return code



def add_child_cache_isolation(code):
    def change(old, new, label):
        nonlocal code

        count = code.count(old)
        if count != 1:
            raise RuntimeError(
                "Cache patch %s: expected 1 match, found %d"
                % (label, count)
            )

        code = code.replace(old, new, 1)

    change(
        """import importlib.util
import json""",
        """import importlib.util
import json
import uuid""",
        "uuid import"
    )

    change(
        "CACHE.mkdir(parents=True, exist_ok=True)",
        """# Unique cache for this individual child lifetime.
# Never reuse TS fragments from an earlier session.
CACHE = CACHE / ("instance-" + uuid.uuid4().hex)
CACHE.mkdir(parents=True, exist_ok=True)""",
        "unique cache directory"
    )

    return code


RENEW_PATCH = runpy.run_path(
    str(ROOT / "VLC-HLS-URLRenew-Patch-CANDIDATE.py")
)["apply"]


def start_child(video_id):
    if len(SESSIONS) >= MAX_SESSIONS:
        raise RuntimeError("Session limit reached")

    used = {s["port"] for s in SESSIONS.values()}

    port = next(
        (
            p for p in CHILD_PORTS
            if p not in used and port_available(p)
        ),
        None
    )

    if port is None:
        raise RuntimeError("No available child port")

    # Create only gateway-owned candidate files.
    child = ROOT / (
        "VLC-HLS-MultiChild-%d-CANDIDATE.py" % port
    )

    code = TEMPLATE.replace(
        "PORT = 18751",
        "PORT = %d" % port
    ).replace(
        '"HLS-SIDX-VariableURL-CACHE-CANDIDATE"',
        '"%s"' % CACHE_NAME
    )

    code = add_child_activity_tracking(code)
    code = add_child_cache_isolation(code)
    code = RENEW_PATCH(code)

    old_resolver = "YouTube-ResolveDirect-CANDIDATE.py"
    new_resolver = "YouTube-ResolveDirect-RETRY-CANDIDATE.py"

    if code.count(old_resolver) != 1:
        raise RuntimeError(
            "Expected exactly one child resolver reference; found %d"
            % code.count(old_resolver)
        )

    code = code.replace(old_resolver, new_resolver, 1)

    compile(code, str(child), "exec")

    if child.exists():
        if child.read_text(encoding="utf-8") != code:
            raise RuntimeError(
                "Existing child file differs: %s" % child.name
            )
    else:
        child.write_text(code, encoding="utf-8")

    logs = ROOT / "HLS-MultiVideo-LOGS-CANDIDATE"
    logs.mkdir(exist_ok=True)

    log_path = logs / ("%s-%d.log" % (video_id, port))
    log_handle = log_path.open("ab")

    youtube_url = (
        "https://www.youtube.com/watch?v=" + video_id
    )

    print(
        "START SESSION | %s | port %d" % (video_id, port),
        flush=True
    )

    session_token = new_session_token()
    child_env = os.environ.copy()
    child_env["YTVLC_SESSION_TOKEN"] = session_token

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(child), youtube_url],
            cwd=str(ROOT),
            env=child_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=HIDE
        )
    except Exception:
        log_handle.close()
        raise

    session = {
        "created_at": time.time(),
        "last_open": time.time(),
        "video_id": video_id,
        "port": port,
        "session_token": session_token,
        "proc": proc,
        "log_handle": log_handle,
        "log_path": log_path,
        "playlist": (
            "http://127.0.0.1:%d/s/%s/playlist.m3u8"
            % (port, session_token)
        ),
    }

    # The child resolves both media URLs and builds both
    # SIDX indexes before its HTTP listener starts.
    deadline = time.monotonic() + 240

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break

        if child_healthy(session):
            print(
                "READY SESSION | %s | port %d"
                % (video_id, port),
                flush=True
            )
            return session

        time.sleep(0.5)

    stop_child(session)

    raise RuntimeError(
        "Child did not initialize. See %s" % log_path
    )




def child_activity(session):
    address = (
        "http://127.0.0.1:%d/s/%s/activity"
        % (session["port"], session["session_token"])
    )

    with urllib.request.urlopen(
        address, timeout=3
    ) as response:
        return json.loads(response.read())


def is_idle(session):
    # A running segment request must never be reaped.
    # If activity cannot be checked, preserve the child.
    if session["proc"].poll() is not None:
        return True

    try:
        activity = child_activity(session)
    except Exception:
        return False

    if activity["active_requests"] > 0:
        return False

    last = max(
        session["last_open"],
        activity["last_segment_request"]
    )

    idle_seconds = time.time() - last

    if idle_seconds >= SESSION_IDLE_NOTICE_SECONDS:
        if not session.get("idle_notice_logged", False):
            print(
                "IDLE NOTICE | %s | %.0f seconds"
                % (session["video_id"], idle_seconds),
                flush=True
            )
            session["idle_notice_logged"] = True
    else:
        session["idle_notice_logged"] = False

    return idle_seconds >= SESSION_IDLE_SECONDS


def reap_idle_sessions():
    for video_id, session in list(SESSIONS.items()):
        if is_idle(session):
            print(
                "CLEANUP IDLE | %s | port %d"
                % (video_id, session["port"]),
                flush=True
            )
            stop_child(session)
            del SESSIONS[video_id]


def get_session(video_id):
    with LOCK:
        # Cleanup runs when a new gateway request arrives.
        reap_idle_sessions()

        existing = SESSIONS.get(video_id)

        if existing is not None:
            expired = (
                time.time() - existing["created_at"]
                >= SESSION_MAX_AGE
            )

            healthy = child_healthy(existing)

            # Never stop an active child merely because
            # its session has reached the age threshold.
            if healthy and (not expired or not is_idle(existing)):
                existing["last_open"] = time.time()

                print(
                    "REUSE SESSION | %s | port %d"
                    % (video_id, existing["port"]),
                    flush=True
                )
                return existing

            print(
                "REFRESH SESSION | %s | expired=%s healthy=%s"
                % (video_id, expired, healthy),
                flush=True
            )

            stop_child(existing)
            del SESSIONS[video_id]

        session = start_child(video_id)
        SESSIONS[video_id] = session
        return session



# ===== 18759 CACHE LIFECYCLE =====

_original_start_child = start_child
_original_stop_child = stop_child


def _instance_directories(video_id):
    root = ROOT / CACHE_NAME / video_id
    if not root.is_dir():
        return set()

    return {
        p.resolve()
        for p in root.iterdir()
        if p.is_dir()
        and p.name.startswith("instance-")
    }


def start_child(video_id):
    before = _instance_directories(video_id)
    session = _original_start_child(video_id)
    after = _instance_directories(video_id)

    created = after - before

    session["instance_cache"] = (
        next(iter(created)) if len(created) == 1 else None
    )

    if len(created) != 1:
        print(
            "CACHE TRACKING WARNING | %s | count=%d"
            % (video_id, len(created)),
            flush=True
        )

    return session


def stop_child(session):
    _original_stop_child(session)

    proc = session.get("proc")
    if proc is None or proc.poll() is None:
        print("CACHE PRESERVED | child still running", flush=True)
        return

    directory = session.get("instance_cache")
    if directory is None:
        return

    directory = Path(directory).resolve()
    parent = (ROOT / CACHE_NAME / session["video_id"]).resolve()

    if (
        directory.parent != parent
        or not directory.name.startswith("instance-")
        or not directory.is_dir()
        or directory.is_symlink()
    ):
        print("CACHE PRESERVED | unsafe path", flush=True)
        return

    try:
        shutil.rmtree(directory)
        print(
            "CACHE REMOVED | %s" % session["video_id"],
            flush=True
        )
    except OSError as error:
        print(
            "CACHE CLEANUP FAILED | %s" % type(error).__name__,
            flush=True
        )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.path != "/control/shutdown":
            self.send_error(404)
            return

        supplied = self.headers.get(
            "X-HLS-Shutdown-Token", ""
        )

        if (
            self.client_address[0] != "127.0.0.1"
            or not hmac.compare_digest(
                supplied, SHUTDOWN_TOKEN
            )
        ):
            self.send_error(403)
            return

        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.wfile.flush()

        print("GRACEFUL SHUTDOWN REQUESTED", flush=True)

        threading.Thread(
            target=server.shutdown,
            daemon=True
        ).start()

    def do_GET(self):
        if self.path == "/health":
            data = b"MULTIVIDEO_GATEWAY_OK"
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if not self.path.startswith("/video/"):
            self.send_error(404)
            return

        try:
            request = self.path[len("/video/"):]
            supplied, separator, encoded = request.partition("/")

            if not separator or not verify_token(
                supplied, INSTALL_TOKEN
            ):
                self.send_error(403)
                return


            if len(encoded) > 4096:
                raise ValueError("Encoded URL too long")

            url = bytes.fromhex(encoded).decode("utf-8")
            video_id = video_id_from_url(url)

        except (ValueError, UnicodeError) as error:
            self.send_error(400, str(error))
            return

        try:
            session = get_session(video_id)

            self.send_response(302)
            self.send_header(
                "Location", session["playlist"]
            )
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            print(
                "REDIRECT | %s -> %d"
                % (video_id, session["port"]),
                flush=True
            )

        except Exception as error:
            print(
                "SESSION ERROR | %s | %s"
                % (video_id, error),
                flush=True
            )
            self.send_error(
                503, "HLS session initialization failed"
            )


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


print("===== MULTI-VIDEO HLS GATEWAY =====")
print("Gateway port:", PORT)
print("Session age threshold:", SESSION_MAX_AGE, "seconds")
print("Idle cleanup threshold:", SESSION_IDLE_SECONDS, "seconds")
print("Child ports: 18960-18979")
print("Maximum simultaneous sessions:", MAX_SESSIONS)
print("Cache:", CACHE_NAME)
print("Production unchanged")
print("18750 / 18751 / 18752 unchanged")
print()

INSTALL_TOKEN = load_install_token()

server = Server(("127.0.0.1", PORT), Handler)

SHUTDOWN_TOKEN = secrets.token_urlsafe(32)
TOKEN_FILE = ROOT / "HLS-Lifecycle-18761.token"
TOKEN_FILE.write_text(
    SHUTDOWN_TOKEN, encoding="ascii"
)

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nStopping gateway...")
finally:
    server.server_close()

    with LOCK:
        for session in list(SESSIONS.values()):
            stop_child(session)

        SESSIONS.clear()

    try:
        if (
            TOKEN_FILE.exists()
            and TOKEN_FILE.read_text(encoding="ascii")
                == SHUTDOWN_TOKEN
        ):
            TOKEN_FILE.unlink()
    except OSError:
        print("TOKEN CLEANUP FAILED", flush=True)

    print("Gateway-owned child processes stopped.")
