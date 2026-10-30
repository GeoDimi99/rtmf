"""
Shared helpers of the tooling tests (standard library only, plus the PyYAML
and docker modules the tooling needs anyway).

- puts tooling/, tooling/builder/ and tooling/deploy-manager/ on sys.path
- FakeRedis: in-memory hashes, values encoded as redis-py encodes them
- FakeDocker: records containers.run() calls instead of starting containers
- manifests(): the legacy manifests the equivalence tests run on, and where the
  golden files recorded from them are
"""

import importlib
import importlib.util
import logging
import socket
import sys
import types
from pathlib import Path

import docker

TOOLING = Path(__file__).resolve().parents[1]
REPO = TOOLING.parent
for p in (TOOLING, TOOLING / "builder", TOOLING / "deploy-manager"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

IMPLEMENTATIONS = {
    "orchestration-grpc": ("orchestration", "grpc"),
    "orchestration-mqueue": ("orchestration", "mqueue"),
    "choreography-mqueue": ("choreography", "mqueue"),
    "choreography-zeromq": ("choreography", "zeromq"),
}


# --- Redis -------------------------------------------------------------------

def encode_like_redis_py(value) -> str:
    """What redis-py stores for a value (redis.connection.Encoder.encode)."""
    if isinstance(value, bool) or value is None:
        raise TypeError(f"redis-py refuses {value!r}")
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, str):
        return value
    raise TypeError(f"redis-py refuses {type(value).__name__}")


class FakeRedis:
    def __init__(self, *args, **kwargs):
        self.data = {}

    def hset(self, name, key=None, value=None, mapping=None):
        h = self.data.setdefault(name, {})
        items = list((mapping or {}).items()) + ([(key, value)] if key is not None else [])
        for k, v in items:
            h[str(k)] = encode_like_redis_py(v)
        return len(items)

    def set(self, name, value, nx=False, ex=None):
        if nx and name in self.data:
            return None
        self.data[name] = encode_like_redis_py(value)
        return True

    def get(self, name):
        value = self.data.get(name)
        return value if isinstance(value, str) else None

    def delete(self, *names):
        return sum(1 for n in names if self.data.pop(n, None) is not None)

    def scan_iter(self):
        return iter(list(self.data))

    def hgetall(self, name):
        value = self.data.get(name, {})
        return dict(value) if isinstance(value, dict) else {}




# --- Docker ------------------------------------------------------------------

class FakeContainer:
    def __init__(self, name, network, labels=None, owner=None):
        self.name = name
        self.short_id = "0000"
        self.status = "running"
        self.labels = labels or {}
        self.attrs = {"NetworkSettings": {"Networks": {network: {}}}}
        self.owner = owner

    def stop(self):
        self.status = "exited"

    def remove(self):
        if self.owner is not None:
            self.owner.alive.pop(self.name, None)


class FakeContainers:
    def __init__(self, network):
        self.network = network
        self.runs = []          # every containers.run() call, in order
        self.alive = {}         # name -> FakeContainer started and not removed

    def get(self, name):
        if name == socket.gethostname():          # the deploy-manager's own container
            return FakeContainer(name, self.network)
        if name in self.alive:
            return self.alive[name]
        raise docker.errors.NotFound(f"no container {name}")

    def run(self, **kwargs):
        self.runs.append(kwargs)
        c = FakeContainer(kwargs.get("name"), self.network, kwargs.get("labels"), owner=self)
        self.alive[c.name] = c
        return c

    def list(self, all=False, filters=None):
        label = (filters or {}).get("label")
        return [c for c in self.alive.values() if label is None or label in c.labels]


class FakeImage:
    def __init__(self, tag):
        self.id = "sha256:" + tag.replace("/", "_").replace(":", "_")


class FakeImages:
    def __init__(self):
        self.ids = {}           # tag -> ID; unknown tags get a made-up ID

    def get(self, tag):
        image = FakeImage(tag)
        image.id = self.ids.get(tag, image.id)
        return image


class FakeVolume:
    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def remove(self, force=False):
        self.owner.events.append(("remove", self.name))


class FakeVolumes:
    def __init__(self):
        self.events = []

    def get(self, name):
        return FakeVolume(self, name)

    def create(self, name):
        self.events.append(("create", name))


class FakeDocker:
    def __init__(self, network="rtmo_default"):
        self.containers = FakeContainers(network)
        self.images = FakeImages()
        self.volumes = FakeVolumes()


# --- manifests ---------------------------------------------------------------

def manifests():
    """Legacy manifests to test on: the fixtures, and on the benchmarks branch the legacy
    version of every scenario (benchmarks/golden/<scenario>/legacy.yaml)."""
    files = sorted((TOOLING / "tests" / "fixtures").glob("*.yaml"))
    files += sorted((REPO / "benchmarks" / "golden").glob("*/legacy.yaml"))
    return files


def golden_dir(manifest: Path) -> Path:
    """Where the output the legacy tooling produced from a test manifest is recorded."""
    if manifest.parent == TOOLING / "tests" / "fixtures":
        return TOOLING / "tests" / "golden" / manifest.stem
    return manifest.parent          # benchmarks/golden/<scenario>/, next to legacy.yaml


def label(manifest: Path) -> str:
    """Short name of a test manifest for test reports."""
    return manifest.parent.name if manifest.name == "legacy.yaml" else manifest.stem
