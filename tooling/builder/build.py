"""
Builds the images of a manifest with the Docker SDK.

Order: task-wrapper base image (from the local checkout), one image per
manifest image (base + task sources), execution manager for orchestration.
Every step stops at the first failure.
"""

import os
from pathlib import Path
from string import Template
from typing import Callable, Optional

import docker

from build_profiles import BuildProfile
from dsl import Manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "templates" / "Dockerfile.task"


class BuildError(Exception):
    pass


def render_task_dockerfile(profile: BuildProfile, source_dir: str) -> str:
    """Dockerfile of one task image, built on the profile's base image."""
    return Template(TEMPLATE.read_text()).substitute(
        base_image=profile.base_image,
        source_dir=source_dir,
        cmake_args=profile.cmake_args,
        entrypoint=profile.entrypoint,
    )


class Builder:
    def __init__(self, client=None, log: Callable[[str], None] = print):
        self.client = client if client is not None else docker.from_env()
        self.log = log

    def _build(self, context: Path, dockerfile: str, tag: str, no_cache: bool) -> None:
        self.log(f"building {tag}")
        try:
            for chunk in self.client.api.build(path=str(context), dockerfile=dockerfile, tag=tag,
                                               decode=True, rm=True, pull=False, nocache=no_cache):
                if "error" in chunk:
                    raise BuildError(f"{tag}: {chunk['error'].strip()}")
        except docker.errors.DockerException as e:
            raise BuildError(f"{tag}: {e}") from None

    def build_base(self, profile: BuildProfile, no_cache: Optional[bool] = None) -> None:
        self._build(REPO_ROOT, profile.base_dockerfile, profile.base_image,
                    profile.no_cache if no_cache is None else no_cache)

    def build_execution_manager(self, profile: BuildProfile, tag: str, no_cache: Optional[bool] = None) -> None:
        if profile.needs_execution_manager:
            self._build(REPO_ROOT, profile.execution_manager_dockerfile, tag,
                        profile.no_cache if no_cache is None else no_cache)

    def build_tasks(self, profile: BuildProfile, manifest: Manifest, no_cache: Optional[bool] = None) -> None:
        """One image per manifest image, tagged with its name; sources are relative to the manifest."""
        context = Path(manifest.path).resolve().parent if manifest.path else Path.cwd()
        no_cache = profile.no_cache if no_cache is None else no_cache
        for img in manifest.images:
            src = context / img.src
            if not src.is_dir():
                raise BuildError(f"image {img.name!r}: source folder {src} does not exist")
            dockerfile = src / f"Dockerfile.{img.name}"
            dockerfile.write_text(render_task_dockerfile(profile, img.src))
            try:
                self._build(context, os.path.relpath(dockerfile, context), img.name, no_cache)
            finally:
                dockerfile.unlink(missing_ok=True)
