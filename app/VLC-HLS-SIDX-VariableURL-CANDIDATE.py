import importlib.util
import argparse
import hashlib
from urllib.parse import urlparse, parse_qs
import math
import re
import struct
import subprocess
import threading
import time
import urllib.request

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from youtube_vlc_dependencies import find_executable

ROOT = Path(__file__).resolve().parent
PORT = 18751

parser = argparse.ArgumentParser()
parser.add_argument("youtube_url")
args = parser.parse_args()

parsed = urlparse(args.youtube_url)

if parsed.hostname not in (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be"
):
    raise SystemExit("Expected a YouTube URL.")

if parsed.hostname == "youtu.be":
    video_id = parsed.path.strip("/")
else:
    video_id = parse_qs(
        parsed.query
    ).get("v", [""])[0]

if not video_id or not re.fullmatch(
    r"[A-Za-z0-9_-]{11}", video_id
):
    raise SystemExit("Invalid YouTube video ID.")

TEST_URL = (
    "https://www.youtube.com/watch?v=" + video_id
)

# TEST_URL is supplied by the command-line argument.

FFMPEG = find_executable("ffmpeg.exe")
AUDIO_SOURCE = ROOT / "YouTube-AudioOnly-CANDIDATE.m4a"

CACHE = (
    ROOT / "HLS-SIDX-VariableURL-CACHE-CANDIDATE"
    / video_id
)

if not Path(FFMPEG).is_file():
    raise SystemExit("FFmpeg is missing.")

CACHE.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "resolver",
    ROOT / "YouTube-ResolveDirect-CANDIDATE.py"
)

resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)

print("Resolving YouTube test video...", flush=True)
resolved = resolver.resolve(TEST_URL)

if (
    not isinstance(resolved, (tuple, list))
    or len(resolved) != 2
    or not all(
        isinstance(value, str)
        and value.startswith(("https://", "http://"))
        for value in resolved
    )
):
    raise SystemExit(
        "Resolver did not return both video and audio URLs. "
        "No server started."
    )

VIDEO_URL, AUDIO_URL = resolved


def fetch_range(start, end):
    expected = end - start + 1

    request = urllib.request.Request(
        VIDEO_URL,
        headers={
            "Range": "bytes=%d-%d" % (start, end),
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "identity"
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        status = response.status
        content_range = response.headers.get(
            "Content-Range", ""
        )
        data = response.read(expected + 1)

    if status != 206:
        raise RuntimeError("Range HTTP status: %d" % status)

    if len(data) != expected:
        raise RuntimeError("Incomplete range response")

    if not content_range.startswith(
        "bytes %d-%d/" % (start, end)
    ):
        raise RuntimeError("Incorrect Content-Range")

    return data


def run_ffmpeg(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90
    )

    if result.returncode:
        raise RuntimeError(
            "FFmpeg failed:\n" + result.stderr[-2000:]
        )


print("Retrieving video MP4 index...", flush=True)

# First 64 KiB is enough for the tested video.
HEAD = fetch_range(0, 65535)

position = 0
sidx_offset = None
sidx_size = None

while position + 8 <= len(HEAD):
    size, kind = struct.unpack_from(
        ">I4s", HEAD, position
    )

    if size == 1:
        raise RuntimeError("Extended MP4 boxes unsupported")

    if kind == b"sidx":
        sidx_offset = position
        sidx_size = size
        break

    if size < 8:
        raise RuntimeError("Invalid MP4 box size")

    position += size

if sidx_offset is None:
    raise RuntimeError("No SIDX found")

if sidx_offset + sidx_size > len(HEAD):
    raise RuntimeError("SIDX exceeds retrieved header")

# All bytes through the end of SIDX are the initialization
# prefix needed to decode independently fetched fragments.
INIT = HEAD[:sidx_offset + sidx_size]

p = sidx_offset + 8
version = HEAD[p]
p += 4

reference_id, timescale = struct.unpack_from(
    ">II", HEAD, p
)
p += 8

if version == 0:
    earliest, first_offset = struct.unpack_from(
        ">II", HEAD, p
    )
    p += 8
elif version == 1:
    earliest, first_offset = struct.unpack_from(
        ">QQ", HEAD, p
    )
    p += 16
else:
    raise RuntimeError("Unsupported SIDX version")

reserved, count = struct.unpack_from(">HH", HEAD, p)
p += 4

if not timescale or not 1 <= count <= 10000:
    raise RuntimeError("Invalid index values")

ENTRIES = []
offset = sidx_offset + sidx_size + first_offset
ticks = earliest

for index in range(count):
    if p + 12 > sidx_offset + sidx_size:
        raise RuntimeError("Truncated SIDX")

    reference, duration, sap = struct.unpack_from(
        ">III", HEAD, p
    )
    p += 12

    if reference >> 31:
        raise RuntimeError("Nested SIDX not supported")

    if not (sap >> 31):
        raise RuntimeError(
            "Fragment %d lacks a start access point"
            % index
        )

    size = reference & 0x7fffffff

    ENTRIES.append({
        "start": ticks / timescale,
        "duration": duration / timescale,
        "offset": offset,
        "size": size
    })

    offset += size
    ticks += duration

TOTAL_DURATION = (ticks - earliest) / timescale


def fetch_audio_range(start, end):
    expected = end - start + 1

    request = urllib.request.Request(
        AUDIO_URL,
        headers={
            "Range": "bytes=%d-%d" % (start, end),
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "identity"
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        status = response.status
        content_range = response.headers.get(
            "Content-Range", ""
        )
        data = response.read(expected + 1)

    if status != 206 or len(data) != expected:
        raise RuntimeError("Invalid audio HTTP range response")

    if not content_range.startswith(
        "bytes %d-%d/" % (start, end)
    ):
        raise RuntimeError("Incorrect audio Content-Range")

    return data


def load_audio_index():
    head = fetch_audio_range(0, 65535)

    position = 0

    while position + 8 <= len(head):
        size, kind = struct.unpack_from(
            ">I4s", head, position
        )

        if size < 8:
            raise RuntimeError("Invalid audio MP4 box")

        if kind == b"sidx":
            break

        position += size
    else:
        raise RuntimeError("Audio SIDX not found")

    if position + size > len(head):
        raise RuntimeError("Incomplete audio SIDX")

    init = head[:position + size]

    p = position + 8
    version = head[p]
    p += 4

    reference_id, timescale = struct.unpack_from(
        ">II", head, p
    )
    p += 8

    if version == 0:
        earliest, first_offset = struct.unpack_from(
            ">II", head, p
        )
        p += 8
    elif version == 1:
        earliest, first_offset = struct.unpack_from(
            ">QQ", head, p
        )
        p += 16
    else:
        raise RuntimeError("Unsupported audio SIDX version")

    reserved, count = struct.unpack_from(
        ">HH", head, p
    )
    p += 4

    if not timescale or not 1 <= count <= 10000:
        raise RuntimeError("Invalid audio index")

    if p + count * 12 > position + size:
        raise RuntimeError("Truncated audio index")

    entries = []
    byte_offset = position + size + first_offset
    ticks = earliest

    for i in range(count):
        reference, duration, sap = struct.unpack_from(
            ">III", head, p
        )
        p += 12

        if reference >> 31:
            raise RuntimeError(
                "Nested audio SIDX unsupported"
            )

        fragment_size = reference & 0x7fffffff

        entries.append({
            "index": i,
            "start": ticks / timescale,
            "end": (ticks + duration) / timescale,
            "offset": byte_offset,
            "size": fragment_size
        })

        byte_offset += fragment_size
        ticks += duration

    return init, entries


print("Retrieving audio MP4 index...", flush=True)
AUDIO_INIT, AUDIO_ENTRIES = load_audio_index()


def download_audio_window(start, duration, destination):
    end = start + duration

    selected = [
        entry for entry in AUDIO_ENTRIES
        if entry["start"] < end
        and entry["end"] > start
    ]

    if not selected:
        raise RuntimeError(
            "No audio fragments cover requested interval"
        )

    payload = bytearray(AUDIO_INIT)

    for entry in selected:
        first = entry["offset"]
        last = first + entry["size"] - 1

        payload.extend(
            fetch_audio_range(first, last)
        )

    source_path = destination.with_name(
        destination.stem + "-RANGES.mp4"
    )

    try:
        source_path.write_bytes(payload)

        # Critical: partial fragmented MP4 seeking is relative
        # to the first included audio fragment.
        relative_start = start - selected[0]["start"]

        run_ffmpeg([
            FFMPEG,
            "-hide_banner",
            "-loglevel", "error",
            "-ss", "%.9f" % relative_start,
            "-i", str(source_path),
            "-t", "%.9f" % duration,
            "-map", "0:a:0",
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            str(destination)
        ])

    finally:
        source_path.unlink(missing_ok=True)

    print(
        "  Audio fragments: %s | %d bytes"
        % (
            [entry["index"] for entry in selected],
            len(payload)
        ),
        flush=True
    )


playlist_lines = [
    "#EXTM3U",
    "#EXT-X-VERSION:3",
    "#EXT-X-TARGETDURATION:%d" % math.ceil(
        max(e["duration"] for e in ENTRIES)
    ),
    "#EXT-X-MEDIA-SEQUENCE:0",
    "#EXT-X-PLAYLIST-TYPE:VOD"
]

SESSION_TOKEN = __import__("os").environ["YTVLC_SESSION_TOKEN"]

for index, entry in enumerate(ENTRIES):
    playlist_lines.extend([
        "#EXTINF:%.6f," % entry["duration"],
        "/s/%s/segment_%04d.ts" % (SESSION_TOKEN, index)
    ])

playlist_lines.append("#EXT-X-ENDLIST")

PLAYLIST = (
    "\n".join(playlist_lines) + "\n"
).encode("utf-8")

LOCKS = [threading.Lock() for _ in ENTRIES]


def generate_segment(index):
    entry = ENTRIES[index]

    final = CACHE / ("segment_%04d.ts" % index)

    with LOCKS[index]:
        if final.is_file() and final.stat().st_size:
            print(
                "CACHE HIT %02d" % index,
                flush=True
            )
            return final

        start = entry["start"]
        duration = entry["duration"]

        print(
            "GENERATE %02d | %.3f–%.3fs"
            % (index, start, start + duration),
            flush=True
        )

        started = time.monotonic()

        prefix = "fragment_%04d" % index

        video = CACHE / (prefix + ".mp4")
        audio = CACHE / (prefix + ".m4a")
        temp = CACHE / (prefix + ".partial.ts")

        try:
            if not video.exists():
                first = entry["offset"]
                last = first + entry["size"] - 1

                payload = fetch_range(first, last)
                video.write_bytes(INIT + payload)

                print(
                    "  Video downloaded: %d bytes"
                    % len(payload),
                    flush=True
                )

            if not audio.exists():
                download_audio_window(
                    start,
                    duration,
                    audio
                )

            run_ffmpeg([
                FFMPEG,
                "-hide_banner",
                "-loglevel", "error",
                "-i", str(video),
                "-itsoffset", "%.9f" % start,
                "-i", str(audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c", "copy",
                "-copyts",
                "-mpegts_copyts", "1",
                "-f", "mpegts",
                str(temp)
            ])

            if not temp.exists() or not temp.stat().st_size:
                raise RuntimeError("Empty remuxed segment")

            temp.replace(final)

            print(
                "  READY %02d | %.2fs | %d bytes"
                % (
                    index,
                    time.monotonic() - started,
                    final.stat().st_size
                ),
                flush=True
            )

            return final

        finally:
            # The completed TS is the cache. Temporary MP4
            # and AAC intermediates are discarded.
            for path in (video, audio, temp):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass



# Track continuity offsets in playlist order.
# Cache the adjusted bytes in memory, never on disk.
COUNTER_LOCK = threading.RLock()
COUNTER_RESULTS = {}
COUNTER_LAST = {}


def adjust_served_segment(index, original):
    with COUNTER_LOCK:
        if index in COUNTER_RESULTS:
            print(
                "  COUNTERS %02d | reused" % index,
                flush=True
            )
            return COUNTER_RESULTS[index]

        if len(original) % 188:
            raise RuntimeError("Invalid MPEG-TS packet size")

        adjusted = bytearray(original)

        previous = COUNTER_LAST.get(index - 1)

        if previous is None:
            offsets = {}
            mode = "new seek sequence"
        else:
            offsets = {
                pid: (counter + 1) & 15
                for pid, counter in previous.items()
            }
            mode = "continued from %02d" % (index - 1)

        last_payload = {}

        for pos in range(0, len(adjusted), 188):
            if adjusted[pos] != 0x47:
                raise RuntimeError("MPEG-TS sync lost")

            pid = (
                ((adjusted[pos + 1] & 31) << 8)
                | adjusted[pos + 2]
            )

            control = adjusted[pos + 3]
            adaptation = (control >> 4) & 3

            offset = offsets.get(pid, 0)
            original_cc = control & 15
            new_cc = (original_cc + offset) & 15

            adjusted[pos + 3] = (
                (control & 0xf0) | new_cc
            )

            if adaptation in (1, 3):
                last_payload[pid] = new_cc

        result = bytes(adjusted)

        COUNTER_RESULTS[index] = result
        COUNTER_LAST[index] = last_payload

        print(
            "  COUNTERS %02d | %s | PIDs=%d"
            % (index, mode, len(last_payload)),
            flush=True
        )

        return result


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def send_data(self, content, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(content)

    def do_HEAD(self):
        self.handle_request()

    def do_GET(self):
        self.handle_request()

    def handle_request(self):
        path = self.path.split("?", 1)[0]
        prefix = "/s/" + SESSION_TOKEN + "/"

        if not path.startswith(prefix):
            self.send_error(403)
            return

        path = "/" + path[len(prefix):]

        if path == "/playlist.m3u8":
            print("GET playlist", flush=True)
            self.send_data(
                PLAYLIST,
                "application/vnd.apple.mpegurl"
            )
            return

        match = re.fullmatch(
            r"/segment_(\d{4})\.ts", path
        )

        if not match:
            self.send_error(404)
            return

        index = int(match.group(1))

        if index >= len(ENTRIES):
            self.send_error(404)
            return

        try:
            segment = generate_segment(index)
            data = adjust_served_segment(
                index, segment.read_bytes()
            )

            print(
                "GET segment %02d" % index,
                flush=True
            )

            self.send_data(data, "video/mp2t")

        except Exception as error:
            print(
                "ERROR segment %02d: %s"
                % (index, error),
                flush=True
            )
            self.send_error(500, str(error))


print()
print("===== SIDX ON-DEMAND HLS TEST =====")
print("Port:", PORT)
print("YouTube video ID:", video_id)
print("Indexed fragments:", len(ENTRIES))
print("Duration: %.6fs" % TOTAL_DURATION)
print("Video bytes indexed:", len(INIT))
print("Audio fragments indexed:", len(AUDIO_ENTRIES))
print("Audio mode: direct HTTP byte ranges")
print("Cache:", CACHE)
print()
print("Open in VLC:")
print(
    "http://127.0.0.1:%d/playlist.m3u8" % PORT
)
print()
print("Press Ctrl+C to stop.")
print("Production unchanged.")
print()

server = ThreadingHTTPServer(
    ("127.0.0.1", PORT),
    Handler
)

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nStopping candidate server...")
finally:
    server.server_close()
