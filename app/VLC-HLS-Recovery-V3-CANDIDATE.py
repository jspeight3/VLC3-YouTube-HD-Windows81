import json
import msvcrt
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK_FILE = ROOT / "HLS-18761-recovery.lock"
CACHE = ROOT / "HLS-SIDX-Lifecycle18761-CANDIDATE"
GATEWAY = "VLC-HLS-MultiVideo-Lifecycle-18761-CANDIDATE.py"
CHILD_PREFIX = "VLC-HLS-MultiChild-"
HIDE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def get_processes():
    ps = r'''
Get-CimInstance Win32_Process |
Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe")
} |
Select-Object ProcessId, ParentProcessId,
    Name, CommandLine, CreationDate |
ConvertTo-Json -Compress
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=HIDE
    )
    if result.returncode:
        raise RuntimeError("Process enumeration failed")

    if not result.stdout.strip():
        return []

    data = json.loads(result.stdout)
    return data if isinstance(data, list) else [data]

def primary_python_script(command):
    """Return the primary Python script path, if recognizable."""
    if not command:
        return None

    match = re.match(
        r'^\s*(?:"[^"]*pythonw?\.exe"|[^\s"]*pythonw?\.exe)\s+'
        r'(?:-u\s+)?'
        r'(?:"([^"]+)"|([^\s"]+))(?=\s|$)',
        command,
        flags=re.IGNORECASE
    )

    return (match.group(1) or match.group(2)) if match else None


def gateway_process(p):
    script = primary_python_script(p.get("CommandLine"))
    expected = str(ROOT / GATEWAY)

    return bool(script and script.lower() == expected.lower())


def child_process(p):
    script = primary_python_script(p.get("CommandLine"))

    if not script:
        return False

    for port in range(18960, 18980):
        expected = str(
            ROOT / ("%s%d-CANDIDATE.py" % (CHILD_PREFIX, port))
        )

        if script.lower() == expected.lower():
            return True

    return False


def creation_ms(p):
    value = str(p.get("CreationDate") or "")

    match = re.search(r"/Date\((\d+)", value)
    if not match:
        return None

    return int(match.group(1))

def gateway_healthy():
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:18761/health",
            timeout=2
        ) as response:
            return response.status == 200
    except Exception:
        return False

def audit():
    items = get_processes()

    by_pid = {
        int(p["ProcessId"]): p
        for p in items
    }

    gateways = [
        p for p in items if gateway_process(p)
    ]

    children = [
        p for p in items if child_process(p)
    ]

    print("===== 18761 RECOVERY V3 =====")
    print("Gateway healthy:", gateway_healthy())
    print("Gateway processes:", len(gateways))
    print("Child processes:", len(children))

    for child in children:
        pid = int(child["ProcessId"])
        parent_pid = int(child["ParentProcessId"])
        parent = by_pid.get(parent_pid)

        child_created = creation_ms(child)
        parent_created = (
            creation_ms(parent) if parent else None
        )

        valid_parent = (
            parent is not None
            and gateway_process(parent)
            and child_created is not None
            and parent_created is not None
            and parent_created <= child_created
        )

        print()
        print("Child PID:", pid)
        print("Parent PID:", parent_pid)
        print("Child creation ms:", child_created)
        print("Parent creation ms:", parent_created)

        if valid_parent:
            print("CLASSIFICATION: OWNED — PRESERVE")
        elif parent is not None:
            print("CLASSIFICATION: AMBIGUOUS — PRESERVE")
        elif gateways or gateway_healthy():
            print("CLASSIFICATION: GATEWAY ACTIVE — PRESERVE")
        else:
            print("CLASSIFICATION: ORPHAN CANDIDATE")

    instances = (
        list(CACHE.glob("*/instance-*"))
        if CACHE.exists() else []
    )

    print()
    print("Cache instances:", len(instances))
    print("MODE: DRY RUN — no processes or files modified.")

def main():
    with LOCK_FILE.open("a+b") as lock:
        lock.seek(0)
        lock.write(b"\0")
        lock.flush()
        lock.seek(0)

        deadline = time.monotonic() + 10

        while True:
            try:
                msvcrt.locking(
                    lock.fileno(), msvcrt.LK_NBLCK, 1
                )
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recovery lock busy")
                time.sleep(0.1)

        try:
            audit()
        finally:
            lock.seek(0)
            msvcrt.locking(
                lock.fileno(), msvcrt.LK_UNLCK, 1
            )

if __name__ == "__main__":
    main()
