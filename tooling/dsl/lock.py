"""
The manifest lock: which images `rtmo build` produced for a manifest, by image
ID, so `rtmod apply` runs exactly those (plan section 06).

One lock per manifest and implementation, because a benchmark scenario is
built once for each implementation:
    <manifest folder>/.rtmo/<manifest name>.<coordination>-<technology>.lock.json
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Optional

LOCK_FORMAT = 1


class LockError(Exception):
    pass


def lock_path(manifest_path: str, profile: str) -> Path:
    p = Path(manifest_path).resolve()
    return p.parent / ".rtmo" / f"{p.stem}.{profile}.lock.json"


def manifest_digest(manifest_path: str) -> str:
    return "sha256:" + hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()


def write(manifest_path: str, profile: str, rtmo_version: str, images: Dict[str, str],
          execution_manager: Optional[Dict[str, str]] = None) -> Path:
    """images: {image name: image ID}; execution_manager: {"image": tag, "id": image ID} or None."""
    path = lock_path(manifest_path, profile)
    path.parent.mkdir(exist_ok=True)
    data = {
        "format": LOCK_FORMAT,
        "manifest": Path(manifest_path).name,
        "manifest_digest": manifest_digest(manifest_path),
        "profile": profile,
        "rtmo_version": rtmo_version,
        "built": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "images": images,
        "execution_manager": execution_manager,
    }
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


def read(manifest_path: str, profile: str) -> Dict:
    path = lock_path(manifest_path, profile)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise LockError(f"no lock file {path}: run 'rtmo build' for this manifest first") from None
    except json.JSONDecodeError as e:
        raise LockError(f"{path}: invalid lock file: {e}") from None
    if data.get("format") != LOCK_FORMAT:
        raise LockError(f"{path}: lock format {data.get('format')!r} is not supported")
    if data.get("manifest_digest") != manifest_digest(manifest_path):
        raise LockError(f"{path}: the manifest changed since it was built: run 'rtmo build' again")
    return data
