
def apply(code):
    def change(old, new, label):
        nonlocal code
        count = code.count(old)
        if count != 1:
            raise RuntimeError(
                "%s: expected 1 match, found %d"
                % (label, count)
            )
        code = code.replace(old, new, 1)

    change(
        "import importlib.util\nimport json\nimport uuid",
        "import importlib.util\nimport json\nimport uuid\n"
        "import hashlib\nimport urllib.error",
        "renewal imports"
    )

    start_v = code.index("def fetch_range(start, end):")
    end_v = code.index("def run_ffmpeg(command):")
    start_a = code.index("def fetch_audio_range(start, end):")
    end_a = code.index("def load_audio_index():")

    video_original = code[start_v:end_v]
    audio_original = code[start_a:end_a]

    renewal = """
# Media URL renewal state.
URL_RENEW_LOCK = threading.Lock()
URL_GENERATION = 0
URL_RENEW_READY = False
VIDEO_HEAD_HASH = None
AUDIO_HEAD_HASH = None


def _range_once(url, start, end):
    expected = end - start + 1

    request = urllib.request.Request(
        url,
        headers={
            "Range": "bytes=%d-%d" % (start, end),
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "identity"
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        status = response.status
        content_range = response.headers.get("Content-Range", "")
        data = response.read(expected + 1)

    if status != 206:
        raise RuntimeError("Unexpected media range status")

    if len(data) != expected:
        raise RuntimeError("Incomplete media range")

    if not content_range.startswith(
        "bytes %d-%d/" % (start, end)
    ):
        raise RuntimeError("Incorrect media Content-Range")

    return data


def _renew_media_urls(observed_generation):
    global VIDEO_URL, AUDIO_URL, URL_GENERATION

    with URL_RENEW_LOCK:
        # Another request may already have renewed the URLs.
        if URL_GENERATION != observed_generation:
            return

        if not URL_RENEW_READY:
            raise RuntimeError("Media renewal not initialized")

        print("RENEW URLS | resolving", flush=True)

        fresh = resolver.resolve(TEST_URL)

        if (
            not isinstance(fresh, (tuple, list))
            or len(fresh) != 2
            or not all(
                isinstance(u, str)
                and u.startswith(("http://", "https://"))
                for u in fresh
            )
        ):
            raise RuntimeError("Renewal returned invalid streams")

        new_video, new_audio = fresh

        # Verify both streams before changing either URL.
        video_head = _range_once(new_video, 0, 65535)
        audio_head = _range_once(new_audio, 0, 65535)

        if hashlib.sha256(video_head).digest() != VIDEO_HEAD_HASH:
            raise RuntimeError("Renewed video index differs")

        if hashlib.sha256(audio_head).digest() != AUDIO_HEAD_HASH:
            raise RuntimeError("Renewed audio index differs")

        VIDEO_URL = new_video
        AUDIO_URL = new_audio
        URL_GENERATION += 1

        print(
            "RENEW URLS | compatible indexes confirmed",
            flush=True
        )


def _fetch_with_renewal(media, start, end):
    for attempt in range(2):
        generation = URL_GENERATION
        url = VIDEO_URL if media == "video" else AUDIO_URL

        try:
            return _range_once(url, start, end)

        except urllib.error.HTTPError as error:
            if error.code not in (401, 403, 410) or attempt:
                raise

            print(
                "MEDIA AUTH ERROR | %s | %d"
                % (media, error.code),
                flush=True
            )

            _renew_media_urls(generation)

    raise RuntimeError("Media URL renewal exhausted")


def fetch_range(start, end):
    return _fetch_with_renewal("video", start, end)


def fetch_audio_range(start, end):
    return _fetch_with_renewal("audio", start, end)


"""

    change(video_original, renewal, "video fetch replacement")
    change(audio_original, "", "audio fetch replacement")

    change(
        "AUDIO_INIT, AUDIO_ENTRIES = load_audio_index()",
        """AUDIO_INIT, AUDIO_ENTRIES = load_audio_index()

# Store original media fingerprints after successful
# video and audio SIDX initialization.
VIDEO_HEAD_HASH = hashlib.sha256(HEAD).digest()
AUDIO_HEAD_HASH = hashlib.sha256(
    _range_once(AUDIO_URL, 0, 65535)
).digest()

URL_RENEW_READY = True
print("URL RENEWAL READY", flush=True)""",
        "fingerprint initialization"
    )

    compile(code, "<renewal-child>", "exec")
    return code
