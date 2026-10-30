"""
apply(): bring a manifest up on the device, the same way for every mode
(rtmod apply today, the watch loop later).

1. take the apply lock in Redis
2. stop the containers of the previous apply, reset the profile's volumes
3. remove the previous plan
4. start one task-wrapper container per image (by image ID when a lock is given)
5. wait for the gRPC services to accept connections
6. write the plan (and plan:format) into Redis, record what was applied
7. orchestration: start the execution manager last
"""

from typing import Callable, Dict, Optional

import docker

import encoders
import state
from dsl import Manifest
from readiness import wait_for_socket
from run_profiles import profile_for
from runner import Runner


class ApplyError(Exception):
    pass


def check_lock(client, locked: Dict) -> None:
    """Every image of the lock must exist locally with the locked ID."""
    expected = dict(locked["images"])
    if locked.get("execution_manager"):
        expected[locked["execution_manager"]["image"]] = locked["execution_manager"]["id"]
    for tag, image_id in expected.items():
        try:
            found = client.images.get(tag).id
        except docker.errors.NotFound:
            raise ApplyError(f"image {tag!r} of the lock file is not on this machine") from None
        if found != image_id:
            raise ApplyError(f"image {tag!r} is {found}, the lock file expects {image_id}: "
                             "run 'rtmo build' (or 'rtmo push') again")


def apply(manifest: Manifest, docker_client, redis_client, locked: Optional[Dict] = None,
          version: str = "unknown", log: Callable[[str], None] = print,
          wait_ready: Callable[[str], bool] = wait_for_socket) -> None:
    profile = profile_for(manifest)
    runner = Runner(docker_client)
    if locked is not None:
        check_lock(docker_client, locked)
    image_refs = dict(locked["images"]) if locked else None

    with state.ApplyLock(redis_client):
        stopped = runner.stop_all()
        if stopped:
            log(f"stopped the previous containers: {', '.join(stopped)}")
        runner.reset_volumes(profile)
        state.clear_plan(redis_client)

        for container in runner.run_all(profile, manifest, image_refs):
            log(f"started {container.name}")

        if profile.readiness_socket:
            for img in manifest.images:
                path = profile.readiness_socket(manifest, img.name)
                if not wait_ready(path):
                    raise ApplyError(f"{profile.container_name(img.name)} is not ready on {path}")
            log("all task services are ready")

        encoders.write(redis_client, manifest)
        state.record(redis_client, profile.name, manifest.path or "", locked and locked.get("manifest_digest"), version)
        log(f"plan written to Redis ({encoders.plan_format(manifest)})")

        if profile.execution_manager:
            em_image = locked["execution_manager"]["id"] if locked else f"rtmo/execution-manager:{profile.name}"
            em = runner.run_execution_manager(profile, manifest, em_image)
            log(f"started {em.name}")
