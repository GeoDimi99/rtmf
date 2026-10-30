"""Starts and stops the containers of a manifest with its run profile."""

from typing import Dict, List, Optional

import docker

from dsl import Manifest
from run_profiles import RunProfile

ROLE_LABEL = "rtmo.role"           # "task" or "execution-manager"
PROFILE_LABEL = "rtmo.profile"


class RunnerError(Exception):
    pass


class Runner:
    def __init__(self, client=None):
        self.client = client if client is not None else docker.from_env()

    def _start(self, name: str, image: str, options: Dict, role: str, profile: RunProfile):
        """(Re)start one container; an older container with the same name is removed first."""
        options = dict(options)
        options["labels"] = {ROLE_LABEL: role, PROFILE_LABEL: profile.name}
        try:
            try:
                existing = self.client.containers.get(name)
                existing.stop()
                existing.remove()
            except docker.errors.NotFound:
                pass
            return self.client.containers.run(image=image, name=name, detach=True, **options)
        except docker.errors.DockerException as e:
            raise RunnerError(f"failed to run container {name!r} from image {image!r}: {e}") from None

    def run(self, profile: RunProfile, manifest: Manifest, image: str, image_ref: Optional[str] = None):
        """The container of one manifest image; image_ref (an image ID) overrides the tag."""
        options = profile.options(manifest, image)
        if profile.network:
            options["network"] = profile.network
        return self._start(profile.container_name(image), image_ref or image, options, "task", profile)

    def run_all(self, profile: RunProfile, manifest: Manifest, image_refs: Optional[Dict[str, str]] = None):
        """One container per declared image, in manifest order."""
        refs = image_refs or {}
        return [self.run(profile, manifest, img.name, refs.get(img.name)) for img in manifest.images]

    def run_execution_manager(self, profile: RunProfile, image: str):
        spec = dict(profile.execution_manager)
        name = spec.pop("name")
        return self._start(name, image, spec, "execution-manager", profile)

    def reset_volumes(self, profile: RunProfile) -> None:
        """Recreate the profile's named volumes (empty), as the former start scripts did."""
        for name in profile.reset_volumes:
            try:
                self.client.volumes.get(name).remove(force=True)
            except docker.errors.NotFound:
                pass
            except docker.errors.DockerException as e:
                raise RunnerError(f"cannot remove volume {name!r}: {e}") from None
            self.client.volumes.create(name=name)

    def containers(self) -> List:
        """Every container started by rtmod, running or not."""
        return self.client.containers.list(all=True, filters={"label": ROLE_LABEL})

    def stop_all(self) -> List[str]:
        """Stop and remove every container started by rtmod; returns their names."""
        names = []
        for c in self.containers():
            names.append(c.name)
            try:
                c.stop()
                c.remove()
            except docker.errors.NotFound:
                pass
        return names
