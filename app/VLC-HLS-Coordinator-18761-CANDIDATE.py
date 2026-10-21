import contextlib
import msvcrt
import os
import re
import runpy
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GATEWAY_FILE = ROOT / "VLC-HLS-MultiVideo-Lifecycle-18761-CANDIDATE.py"
AUDIT_FILE = ROOT / "VLC-HLS-Recovery-V3-CANDIDATE.py"
LOCK_FILE = ROOT / "HLS-18761-recovery.lock"
LOG_DIR = ROOT / "HLS-Coordinator-18761-LOGS-CANDIDATE"
LOG_FILE = LOG_DIR / "coordinator.log"
GATEWAY_LOG = LOG_DIR / "gateway.log"
CACHE = ROOT / "HLS-SIDX-Lifecycle18761-CANDIDATE"
HEALTH = "http://127.0.0.1:18761/health"
HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LOG_DIR.mkdir(exist_ok=True)

v3 = runpy.run_path(str(AUDIT_FILE))
get_processes = v3["get_processes"]
gateway_process = v3["gateway_process"]
child_process = v3["child_process"]
creation_ms = v3["creation_ms"]

def healthy():
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as r:
            return r.status == 200 and r.read(128) == b"MULTIVIDEO_GATEWAY_OK"
    except Exception:
        return False

def process_exists(pid):
    ps = (
        "Get-CimInstance Win32_Process "
        '-Filter "ProcessId=%d" | '
        "Select-Object -ExpandProperty ProcessId"
    ) % pid

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=HIDE
    )

    if result.returncode:
        raise RuntimeError("Parent PID inspection failed")

    return str(pid) in result.stdout.split()

def snapshot():
    items = get_processes()
    gateways = [p for p in items if gateway_process(p)]
    children = [p for p in items if child_process(p)]
    return gateways, children

def verify_no_gateway():
    if healthy():
        raise RuntimeError("Gateway became healthy during recovery")

    gateways, _ = snapshot()

    if gateways:
        raise RuntimeError(
            "Gateway process exists but is not ready; "
            "refusing orphan cleanup"
        )

def recover_orphans():
    verify_no_gateway()

    gateways, children = snapshot()

    if not children:
        print("RECOVERY: No orphan children", flush=True)
        return

    print(
        "RECOVERY: %d orphan candidate(s)" % len(children),
        flush=True
    )

    verified = []

    # Validate every candidate before stopping any process.
    for child in children:
        pid = int(child["ProcessId"])
        parent = int(child["ParentProcessId"])
        created = creation_ms(child)
        command = child.get("CommandLine") or ""

        video_match = re.search(
            r"https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})",
            command
        )

        if (
            created is None
            or not video_match
            or process_exists(parent)
        ):
            raise RuntimeError(
                "Ambiguous ownership for PID %d; no cleanup" % pid
            )

        verified.append((
            pid, parent, created, command,
            video_match.group(1)
        ))

    for pid, parent, created, command, video_id in verified:
        verify_no_gateway()

        current = [
            p for p in get_processes()
            if int(p["ProcessId"]) == pid
        ]

        if (
            len(current) != 1
            or not child_process(current[0])
            or int(current[0]["ParentProcessId"]) != parent
            or creation_ms(current[0]) != created
            or (current[0].get("CommandLine") or "") != command
            or process_exists(parent)
        ):
            raise RuntimeError(
                "Process identity changed for PID %d" % pid
            )

        print("RECOVERY: Stopping verified child PID", pid, flush=True)

        result = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            creationflags=HIDE
        )

        if result.returncode:
            raise RuntimeError(
                "Cannot terminate PID %d: %s"
                % (pid, result.stderr.strip())
            )

    time.sleep(0.5)
    verify_no_gateway()

    if snapshot()[1]:
        raise RuntimeError("Child remains; caches preserved")

    # Only remove unambiguous instance directories for the
    # verified video IDs, after all candidate children have exited.
    for video_id in sorted({item[4] for item in verified}):
        parent = CACHE / video_id

        if parent.is_symlink() or not parent.is_dir():
            continue

        instances = list(parent.glob("instance-*"))

        if len(instances) != 1:
            print(
                "RECOVERY: Cache preserved (ambiguous count) |",
                video_id, len(instances),
                flush=True
            )
            continue

        directory = instances[0]

        if (
            directory.is_symlink()
            or not directory.is_dir()
            or directory.resolve().parent != parent.resolve()
        ):
            raise RuntimeError("Unsafe cache directory")

        import shutil
        shutil.rmtree(directory)
        print("RECOVERY: Cache removed |", video_id, flush=True)

def start_gateway():
    pythonw = Path(sys.executable).with_name("pythonw.exe")

    if not pythonw.is_file() or not GATEWAY_FILE.is_file():
        raise RuntimeError("Gateway or pythonw.exe missing")

    with GATEWAY_LOG.open("ab") as log:
        proc = subprocess.Popen(
            [str(pythonw), "-u", str(GATEWAY_FILE)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=HIDE
        )

    deadline = time.monotonic() + 20

    while time.monotonic() < deadline:
        if healthy():
            print("STARTUP: Gateway ready", flush=True)
            return

        if proc.poll() is not None:
            raise RuntimeError(
                "Gateway exited during startup: %s" % proc.returncode
            )

        time.sleep(0.2)

    raise RuntimeError("Gateway readiness timeout")

def main():
    with LOCK_FILE.open("a+b") as lock:
        lock.seek(0)
        lock.write(b"\0")
        lock.flush()
        lock.seek(0)

        deadline = time.monotonic() + 30

        while True:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Startup/recovery lock timeout")
                time.sleep(0.1)

        try:
            if healthy():
                print("STARTUP: Reusing healthy gateway", flush=True)
                return

            recover_orphans()
            verify_no_gateway()
            start_gateway()

        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

if __name__ == "__main__":
    with LOG_FILE.open("a", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log):
            with contextlib.redirect_stderr(log):
                try:
                    print(
                        "\n===== COORDINATOR %s ====="
                        % time.strftime("%Y-%m-%d %H:%M:%S"),
                        flush=True
                    )
                    main()
                except Exception:
                    traceback.print_exc()
                    raise SystemExit(1)
