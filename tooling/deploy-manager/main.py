"""
rtmod: device side of RTMO. Runs in the deploy-manager container; the
installed `rtmod` launcher starts that container with the Docker socket, the
manifest's folder (read-only) and the host network.

    rtmod apply  <manifest> [--no-lock]
    rtmod status [--containers]
    rtmod stop
    rtmod --version

apply takes --coordination, --technology and --iterations like rtmo.
"""

import argparse
import sys

import docker
import redis

import state
from apply import ApplyError, apply
from dsl import ManifestError, parse, validate
from dsl import lock
from dsl.overrides import add_arguments, from_arguments, override, read
from dsl.version import describe, version
from runner import ROLE_LABEL, Runner, RunnerError

REDIS_HOST, REDIS_PORT = "localhost", 6379   # published by device/compose.yaml


def log(msg: str) -> None:
    print(f"[rtmod] {msg}", flush=True)


def redis_client():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def cmd_apply(args) -> int:
    manifest = parse(override(read(args.manifest), **from_arguments(args)))
    manifest.path = args.manifest
    errors, warnings = validate(manifest)
    for w in warnings:
        log(f"warning: {w}")
    if errors:
        for e in errors:
            log(f"error: {e}")
        return 1
    locked = None if args.no_lock else lock.read(args.manifest, manifest.deployment.profile)
    apply(manifest, docker.from_env(), redis_client(), locked, version=version(), log=log)
    log(f"applied {args.manifest} ({manifest.deployment.profile})")
    return 0


def cmd_status(args) -> int:
    runner = Runner(docker.from_env())
    containers = runner.containers()
    if args.containers:
        for c in containers:
            print(c.labels.get(ROLE_LABEL, "?"), c.name)
        return 0
    applied = state.read(redis_client())
    if not applied:
        print("nothing applied")
    for key in ("profile", "manifest", "status", "applied_at", "stopped_at", "rtmo_version", "manifest_digest"):
        if applied.get(key):
            print(f"{key:16} {applied[key]}")
    for c in containers:
        print(f"{'container':16} {c.name} ({c.labels.get(ROLE_LABEL, '?')}, {c.status})")
    return 0


def cmd_stop(args) -> int:
    names = Runner(docker.from_env()).stop_all()
    state.mark_stopped(redis_client())
    log(f"stopped {', '.join(names) if names else 'nothing'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rtmod", description="RTMO device tools: apply, inspect and stop a manifest.")
    ap.add_argument("--version", action="version", version=f"rtmod {describe()}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("apply", help="start the containers of a manifest and write its plan into Redis")
    p.add_argument("manifest")
    p.add_argument("--no-lock", action="store_true", help="run the images by tag, without checking a lock file")
    add_arguments(p)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("status", help="what is applied and which containers exist")
    p.add_argument("--containers", action="store_true", help="only list the containers: <role> <name> per line")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("stop", help="stop and remove the containers started by rtmod")
    p.set_defaults(func=cmd_stop)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ManifestError, lock.LockError, ApplyError, RunnerError, state.LockedError) as e:
        log(f"error: {e}")
        return 1
    except redis.exceptions.ConnectionError as e:
        log(f"error: Redis is not reachable on {REDIS_HOST}:{REDIS_PORT} ({e}); "
            "start it with: docker compose -f device/compose.yaml up -d")
        return 1


if __name__ == "__main__":
    sys.exit(main())
