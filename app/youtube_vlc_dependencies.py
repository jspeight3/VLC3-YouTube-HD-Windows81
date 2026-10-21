"""Executable discovery for the portable YouTubeVLC application."""

from pathlib import Path
import shutil


APP_DIR = Path(__file__).resolve().parent


def find_executable(name):
    """Prefer an executable beside this module, then use PATH."""
    if Path(name).name != name:
        raise ValueError("Expected an executable filename")

    local = APP_DIR / name

    if local.is_file():
        return str(local)

    found = shutil.which(name)

    if found:
        return str(Path(found).resolve())

    raise FileNotFoundError(
        "Missing executable: %s. Place it in the application "
        "folder or make it available through PATH." % name
    )
