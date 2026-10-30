"""
rtmo: developer side of RTMO.

    rtmo validate <manifest> [--print profile|manifest]
    rtmo build    <manifest> [--no-cache]
    rtmo push     <manifest> --ssh user@device [--dest /srv/rtmo/apps/<app>]
    rtmo --version

Every command takes --coordination, --technology and --iterations to override
the manifest (benchmark campaigns run one scenario on every implementation).
Run with tooling/ on PYTHONPATH (the installed launcher does this).
"""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from dsl import ManifestError, parse, validate
from dsl import lock
from dsl.overrides import add_arguments, from_arguments, override, read
from dsl.version import describe, version


def log(msg: str) -> None:
    print(f"[rtmo] {msg}", file=sys.stderr, flush=True)


def load_manifest(args):
    """Manifest with overrides applied, validated; exits on errors."""
    data = override(read(args.manifest), **from_arguments(args))
    manifest = parse(data)
    manifest.path = str(Path(args.manifest).resolve())
    errors, warnings = validate(manifest)
    for w in warnings:
        log(f"warning: {w}")
    if errors:
        for e in errors:
            log(f"error: {e}")
        sys.exit(1)
    return manifest, data


def cmd_validate(args) -> int:
    manifest, data = load_manifest(args)
    if args.print == "profile":
        print(manifest.deployment.profile)
    elif args.print == "manifest":
        sys.stdout.write(yaml.safe_dump(data, sort_keys=False, default_flow_style=False, width=100))
    else:
        log(f"{args.manifest}: valid ({manifest.deployment.profile}, "
            f"{len(manifest.images)} images, {len(manifest.schedule.tasks)} tasks)")
    return 0


def cmd_build(args) -> int:
    from build import BuildError, Builder
    from build_profiles import profile_for

    manifest, _ = load_manifest(args)
    profile = profile_for(manifest)
    builder = Builder(log=log)
    try:
        builder.build_base(profile, no_cache=True if args.no_cache else None)
        images = builder.build_tasks(profile, manifest, no_cache=True if args.no_cache else None)
        em_id = builder.build_execution_manager(profile, no_cache=args.no_cache)
    except BuildError as e:
        log(f"error: build failed: {e}")
        return 1
    em = {"image": profile.execution_manager_image, "id": em_id} if em_id else None
    path = lock.write(manifest.path, profile.name, version(), images, em)
    log(f"built {len(images)} task image(s){' + execution manager' if em else ''}; lock: {path}")
    return 0


def cmd_push(args) -> int:
    manifest, _ = load_manifest(args)
    profile = manifest.deployment.profile
    try:
        locked = lock.read(manifest.path, profile)
    except lock.LockError as e:
        log(f"error: {e}")
        return 1
    tags = list(locked["images"]) + ([locked["execution_manager"]["image"]] if locked["execution_manager"] else [])
    dest = args.dest or f"/srv/rtmo/apps/{Path(manifest.path).parent.name}"
    host = args.ssh
    log(f"sending {len(tags)} image(s) to {host}")
    save = "docker save " + " ".join(shlex.quote(t) for t in tags)
    if subprocess.run(f"{save} | ssh {shlex.quote(host)} docker load", shell=True).returncode != 0:
        log("error: sending the images failed")
        return 1
    lock_file = lock.lock_path(manifest.path, profile)
    steps = [
        ["ssh", host, "mkdir", "-p", f"{dest}/.rtmo"],
        ["scp", "-q", manifest.path, f"{host}:{dest}/"],
        ["scp", "-q", str(lock_file), f"{host}:{dest}/.rtmo/"],
    ]
    for step in steps:
        if subprocess.run(step).returncode != 0:
            log(f"error: {' '.join(step)} failed")
            return 1
    log(f"done: on the device run  rtmod apply {dest}/{Path(manifest.path).name}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rtmo", description="RTMO developer tools: validate, build and push manifests.")
    ap.add_argument("--version", action="version", version=f"rtmo {describe()}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a manifest")
    p.add_argument("--print", choices=["profile", "manifest"],
                   help="print the implementation name or the manifest with the overrides applied")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("build", help="build the images of a manifest and write its lock file")
    p.add_argument("--no-cache", action="store_true", help="build every image without the Docker cache")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("push", help="send the images, manifest and lock file to a device over SSH")
    p.add_argument("--ssh", required=True, metavar="USER@HOST")
    p.add_argument("--dest", help="folder on the device (default: /srv/rtmo/apps/<folder of the manifest>)")
    p.set_defaults(func=cmd_push)

    for p in sub.choices.values():
        p.add_argument("manifest")
        add_arguments(p)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ManifestError as e:
        log(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
