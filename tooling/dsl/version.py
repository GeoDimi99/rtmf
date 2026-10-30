"""RTMO version: the VERSION file of the checkout, plus the git commit when available."""

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def version() -> str:
    # In the deploy-manager image there is no checkout: the version is passed in the environment.
    env = os.environ.get("RTMO_VERSION")
    if env:
        return env
    try:
        return (REPO / "VERSION").read_text().strip()
    except FileNotFoundError:
        return "unknown"


def describe() -> str:
    """e.g. '0.1.0 (v0.1.0-3-g1a2b3c4)', or just the version outside a git checkout."""
    try:
        commit = subprocess.run(["git", "-C", str(REPO), "describe", "--tags", "--always", "--dirty"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    if not commit:
        commit = os.environ.get("RTMO_COMMIT", "")
    return f"{version()} ({commit})" if commit else version()
