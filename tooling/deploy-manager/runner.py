"""Starts the task-wrapper containers of a manifest with its run profile."""

import socket

import docker

from dsl import Manifest
from run_profiles import RunProfile


class RunnerError(Exception):
    pass


class Runner:
    def __init__(self, client=None):
        self.client = client if client is not None else docker.from_env()

    def own_network(self) -> str:
        """Network of the container this code runs in (the compose network), or 'bridge'."""
        try:
            me = self.client.containers.get(socket.gethostname())
            networks = list(me.attrs["NetworkSettings"]["Networks"].keys())
            return networks[0] if networks else "bridge"
        except docker.errors.DockerException:
            return "bridge"

    def run(self, profile: RunProfile, manifest: Manifest, image: str):
        """(Re)start the container of one image; returns the container."""
        name = profile.container_name(image)
        options = profile.options(manifest, image)
        if profile.join_own_network:
            options["network"] = self.own_network()
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

    def run_all(self, profile: RunProfile, manifest: Manifest):
        """One container per declared image, in manifest order."""
        return [self.run(profile, manifest, img.name) for img in manifest.images]
