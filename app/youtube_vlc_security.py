"""Local authentication for the portable YouTubeVLC application."""

import os
import secrets
import time
from pathlib import Path


def config_directory():
    """Return the user's private configuration directory."""
    local = os.environ.get("LOCALAPPDATA")

    if not local:
        raise RuntimeError("LOCALAPPDATA is unavailable")

    return Path(local) / "YouTubeVLC"


def token_path():
    return config_directory() / "install.token"


def validate_token(value):
    """Validate our URL-safe installation token format."""
    if not isinstance(value, str):
        return False

    if len(value) != 43:
        return False

    return all(
        c.isalnum() or c in "-_"
        for c in value
    )


def get_install_token():
    """Create or load one persistent token, including startup races."""
    directory = config_directory()
    directory.mkdir(parents=True, exist_ok=True)

    path = token_path()

    for attempt in range(20):
        try:
            with path.open("x", encoding="ascii") as handle:
                handle.write(secrets.token_urlsafe(32) + "\n")

        except FileExistsError:
            pass

        try:
            token = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            token = ""

        if validate_token(token):
            return token

        # Another process might still be writing the new file.
        time.sleep(0.05)

    raise RuntimeError(
        "Installation token missing, invalid, or inaccessible"
    )


def verify_token(provided, expected):
    """Constant-time token comparison."""
    if not validate_token(provided):
        return False

    if not validate_token(expected):
        return False

    return secrets.compare_digest(provided, expected)


def new_session_token():
    """Return a fresh token for one video session."""
    return secrets.token_urlsafe(32)


def load_install_token():
    """Read an existing token without creating or replacing it."""
    path = token_path()

    try:
        token = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise RuntimeError(
            "YouTubeVLC installation token is unavailable"
        ) from error

    if not validate_token(token):
        raise RuntimeError(
            "YouTubeVLC installation token is invalid"
        )

    return token
