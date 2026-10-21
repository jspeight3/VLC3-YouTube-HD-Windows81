"""Manual setup utility for YouTubeVLC."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"

sys.path.insert(0, str(APP))

from youtube_vlc_dependencies import find_executable



def persistent_executable(name):
    """Find executable using persistent Windows PATH entries."""
    import subprocess

    if name not in ("yt-dlp.exe", "qjs.exe", "ffmpeg.exe"):
        raise ValueError("Unsupported executable name")

    script = (
        '$name = "' + name + '"; '
        'foreach ($scope in @("Machine","User")) { '
        '$value = [Environment]::GetEnvironmentVariable("Path",$scope); '
        'foreach ($entry in ($value -split ";")) { '
        'if (-not $entry) { continue }; '
        '$directory = [Environment]::ExpandEnvironmentVariables('
        '$entry.Trim([char]34)); '
        '$candidate = Join-Path $directory $name; '
        'if (Test-Path -LiteralPath $candidate -PathType Leaf) { '
        'Write-Output $candidate; exit 0 '
        '} } }; exit 1'
    )

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True, errors="replace",
        check=False
    )

    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip().splitlines()[0])

    return None


def validate():
    print("===== YouTubeVLC Setup Validation =====")

    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required")

    required = (
        "youtube_bridge.lua",
        "app/VLC-AutoStart-18761-CANDIDATE.vbs",
        "app/VLC-HLS-Coordinator-18761-CANDIDATE.py",
        "app/VLC-HLS-MultiVideo-Lifecycle-18761-CANDIDATE.py",
        "app/VLC-HLS-SIDX-VariableURL-CANDIDATE.py",
        "app/VLC-HLS-URLRenew-Patch-CANDIDATE.py",
        "app/VLC-HLS-Recovery-V3-CANDIDATE.py",
        "app/YouTube-ResolveDirect-RETRY-CANDIDATE.py",
        "app/youtube_vlc_dependencies.py",
        "app/youtube_vlc_security.py",
    )

    for filename in required:
        path = ROOT / filename

        if not path.is_file():
            raise RuntimeError("Missing: " + filename)

    print("PASS: Required application files present.")

    for name in ("yt-dlp.exe", "qjs.exe", "ffmpeg.exe"):
        if (APP / name).is_file():
            print("PASS: Local dependency:", name)
        elif persistent_executable(name):
            print("PASS: Persistent PATH dependency:", name)
        else:
            raise RuntimeError(
                name + " is not in app or persistent Windows PATH. "
                "A temporary shell PATH is insufficient for VLC."
            )

    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")

    if not appdata or not localappdata:
        raise RuntimeError(
            "APPDATA or LOCALAPPDATA is unavailable"
        )

    print("PASS: Windows configuration paths available.")
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
    if not pythonw.is_file():
        raise RuntimeError("Matching pythonw.exe was not found")

    print("PASS: Pythonw available.")
    print("PASS: Python version:", sys.version.split()[0])

    print()
    print("Validation complete. No files installed.")


def test_install():
    """Simulate installation without changing real VLC configuration."""
    import shutil
    import tempfile

    from youtube_vlc_security import get_install_token

    with tempfile.TemporaryDirectory(
        prefix="YouTubeVLC-Install-Test-"
    ) as temporary:
        base = Path(temporary)

        test_appdata = base / "Roaming"
        test_localappdata = base / "Local"

        playlist = (
            test_appdata / "vlc" / "lua" / "playlist"
        )
        playlist.mkdir(parents=True)

        original_appdata = os.environ.get("APPDATA")
        original_local = os.environ.get("LOCALAPPDATA")

        try:
            os.environ["APPDATA"] = str(test_appdata)
            os.environ["LOCALAPPDATA"] = str(test_localappdata)

            shutil.copy2(
                ROOT / "youtube_bridge.lua",
                playlist / "00_youtube_bridge.lua"
            )

            (playlist / "youtube_vlc_path.txt").write_text(
                str(APP) + "\n",
                encoding="utf-8"
            )

            first = get_install_token()
            second = get_install_token()

            assert first == second
            assert len(first) == 43

            assert (
                playlist / "00_youtube_bridge.lua"
            ).is_file()

            assert (
                playlist / "youtube_vlc_path.txt"
            ).read_text(encoding="utf-8").strip() == str(APP)

            assert (
                test_localappdata / "YouTubeVLC" / "install.token"
            ).is_file()

            print("PASS: Lua installed in test playlist directory.")
            print("PASS: Application-path configuration generated.")
            print("PASS: Installation token generated and reused.")
            print("PASS: Real VLC configuration untouched.")

        finally:
            if original_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = original_appdata

            if original_local is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = original_local

    print("PASS: Disposable installation removed.")



def install(replace=False):
    """Install bridge and configuration with error rollback."""
    import shutil
    import tempfile
    from youtube_vlc_security import get_install_token

    playlist = Path(os.environ["APPDATA"]) / "vlc" / "lua" / "playlist"
    lua = playlist / "00_youtube_bridge.lua"
    config = playlist / "youtube_vlc_path.txt"
    python_config = APP / "youtube_vlc_pythonw.txt"
    pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")

    if not pythonw.is_file():
        raise RuntimeError("Missing pythonw.exe")

    targets = (lua, config, python_config)
    if not replace and any(p.exists() for p in targets):
        raise RuntimeError("Existing installation: use --replace")

    get_install_token()
    playlist.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="YTVLC-", dir=str(playlist)) as tmp:
        stage = Path(tmp)
        inputs = (
            ROOT / "youtube_bridge.lua",
            None,
            None,
        )
        backups = {}
        staged = {}

        for index, target in enumerate(targets):
            candidate = stage / ("new-%d" % index)
            if inputs[index] is not None:
                shutil.copy2(inputs[index], candidate)
            else:
                value = str(APP) if index == 1 else str(pythonw)
                candidate.write_text(value + chr(10), encoding="utf-8")
            staged[target] = candidate

            if target.exists():
                backup = stage / ("old-%d" % index)
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None

        try:
            for target in targets:
                shutil.copy2(staged[target], target)
        except Exception:
            for target in targets:
                backup = backups[target]
                if backup is None:
                    if target.exists():
                        target.unlink()
                else:
                    shutil.copy2(backup, target)
            raise

    print("PASS: VLC bridge installed.")
    print("PASS: Application and interpreter configured.")
    print("PASS: Installation token initialized.")
    print("Restart VLC before testing.")



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    if args.replace and not args.install:
        parser.error("--replace requires --install")
    if args.test and args.install:
        parser.error("--test and --install cannot be combined")

    validate()

    if args.test:
        test_install()
    elif args.install:
        install(replace=args.replace)
