import os
import time
import subprocess
import sys
from pathlib import Path
from youtube_vlc_dependencies import find_executable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

def resolve_once(url):
    host = (urlsplit(url).hostname or "").lower()
    if host not in {
        "youtube.com", "www.youtube.com",
        "m.youtube.com", "music.youtube.com", "youtu.be"
    }:
        raise ValueError("Unsupported YouTube URL")

    command = [
        find_executable("yt-dlp.exe"),
        "--no-playlist",
        "--no-warnings",
        "--extractor-args", "youtube:player_client=web_embedded",
        "--js-runtimes", "quickjs:" + find_executable("qjs.exe"),
        "--remote-components", "ejs:github",
        "-f",
        "bv[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]",
        "-g",
        "--",
        url
    ]

    env = os.environ.copy()
    env["PATH"] = str(ROOT) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        env=env,
        creationflags=getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        ),
    )

    if result.returncode:
        raise RuntimeError(result.stderr.strip())

    urls = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith(("https://", "http://"))
    ]

    if not urls:
        raise RuntimeError("No direct media URLs returned")

    if len(urls) != 2:
        raise RuntimeError(
            "Expected two separate media URLs; received %d"
            % len(urls)
        )

    return urls



def resolve(url):
    errors = []

    for attempt in range(1, 4):
        try:
            urls = resolve_once(url)

            if attempt > 1:
                print(
                    "Resolver succeeded on attempt %d"
                    % attempt,
                    flush=True
                )

            return urls

        except (RuntimeError, subprocess.TimeoutExpired) as error:
            message = str(error)

            # Do not print exceptions that might contain
            # signed media URLs.
            errors.append(type(error).__name__)

            print(
                "Resolver attempt %d failed (%s)"
                % (attempt, type(error).__name__),
                flush=True
            )

            if attempt < 3:
                time.sleep(attempt * 2)

    raise RuntimeError(
        "Unable to resolve two separate streams "
        "after 3 attempts: %s"
        % ", ".join(errors)
    )



if __name__ == "__main__":
    test_url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://www.youtube.com/watch?v=ToksxXw0e_Q"
    )

    urls = resolve(test_url)

    print("Direct media streams:", len(urls))
    for index, item in enumerate(urls, 1):
        print(
            "Stream %d: %s, URL length %d" %
            (index, urlsplit(item).scheme, len(item))
        )

    print("Resolution successful.")
