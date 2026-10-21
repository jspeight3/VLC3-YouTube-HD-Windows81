from pathlib import Path
from urllib.request import Request, urlopen
import time

root = Path(__file__).resolve().parent
token_file = root / "HLS-Lifecycle-18761.token"
health = "http://127.0.0.1:18761/health"

if not token_file.is_file():
    raise SystemExit("18761 shutdown token missing.")

token = token_file.read_text(encoding="ascii").strip()

request = Request(
    "http://127.0.0.1:18761/control/shutdown",
    data=b"",
    headers={"X-HLS-Shutdown-Token": token},
    method="POST"
)

with urlopen(request, timeout=5) as response:
    if response.status != 202:
        raise RuntimeError("Shutdown request rejected.")

print("Shutdown accepted. Waiting for cleanup...")

deadline = time.monotonic() + 20

while time.monotonic() < deadline:
    try:
        with urlopen(health, timeout=1):
            pass
    except Exception:
        if not token_file.exists():
            print("PASS: Gateway stopped; token removed.")
            break
    time.sleep(0.25)
else:
    raise SystemExit("Shutdown completion not confirmed.")
