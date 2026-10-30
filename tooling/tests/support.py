"""
Shared helpers of the tooling tests (standard library only, plus the PyYAML
and docker modules the tooling needs anyway).

- puts tooling/, tooling/builder/ and tooling/deploy-manager/ on sys.path
- FakeRedis: in-memory hashes, values encoded as redis-py encodes them
- FakeDocker: records containers.run() calls instead of starting containers
- legacy(): imports one legacy deploy-manager under its own package name
- manifests(): the legacy manifests the equivalence tests run on
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

    def set(self, name, value):
        self.data[name] = encode_like_redis_py(value)

    def hgetall(self, name):
        return dict(self.data.get(name, {}))


# The legacy loaders call redis.Redis(...) when they are created.
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=FakeRedis))


# --- Docker ------------------------------------------------------------------

class FakeContainer:
    def __init__(self, name, network):
        self.name = name
        self.short_id = "0000"
        self.attrs = {"NetworkSettings": {"Networks": {network: {}}}}

    def stop(self):
        pass

    def remove(self):
        pass


class FakeContainers:
    def __init__(self, network):
        self.network = network
        self.runs = []

    def get(self, name):
        if name == socket.gethostname():          # the deploy-manager's own container
            return FakeContainer(name, self.network)
        raise docker.errors.NotFound(f"no container {name}")

    def run(self, **kwargs):
        self.runs.append(kwargs)
        return FakeContainer(kwargs.get("name"), self.network)


class FakeDocker:
    def __init__(self, network="rtmo_default"):
        self.containers = FakeContainers(network)


# --- legacy deploy-managers --------------------------------------------------

def legacy(impl: str):
    """The legacy deploy-manager of `impl` as package 'legacy_<impl>' (its src/ folder)."""
    name = "legacy_" + impl.replace("-", "_")
    if name not in sys.modules:
        src = TOOLING / "legacy" / impl / "deploy-manager" / "src"
        spec = importlib.util.spec_from_file_location(name, src / "__init__.py",
                                                      submodule_search_locations=[str(src)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        logging.getLogger("deploy-manager").disabled = True   # the legacy code logs every step
    return types.SimpleNamespace(
        parser=importlib.import_module(f"{name}.manifest.parser"),
        loader=importlib.import_module(f"{name}." + ("database" if impl == "orchestration-grpc" else "redisdb")
                                       + ".redis_loader"),
        runner=importlib.import_module(f"{name}.deploy.runner"),
    )


# --- manifests ---------------------------------------------------------------

def manifests():
    """Legacy manifests to test on: the fixtures, and the benchmark scenarios when present."""
    files = sorted((TOOLING / "tests" / "fixtures").glob("*.yaml"))
    files += sorted((REPO / "benchmarks" / "scenarios").glob("*.yaml"))
    return files


def golden_dir(manifest: Path) -> Path:
    """Where the recorded legacy output of a test manifest lives (see record_golden.py)."""
    if manifest.parent == TOOLING / "tests" / "fixtures":
        return TOOLING / "tests" / "golden" / manifest.stem
    return REPO / "benchmarks" / "golden" / manifest.stem
