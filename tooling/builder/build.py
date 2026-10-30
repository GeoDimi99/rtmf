"""
Builds the images of a manifest with the Docker SDK.

Order: task-wrapper base image (from the local checkout), one image per
manifest image (base + task sources), execution manager for orchestration.
Every step stops at the first failure.
"""

import os
from pathlib import Path
from string import Template
from typing import Callable, Dict, Optional

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

    def _build(self, context: Path, dockerfile: str, tag: str, no_cache: bool) -> str:
        """Build one image; returns its image ID."""
        self.log(f"building {tag}")
        try:
            for chunk in self.client.api.build(path=str(context), dockerfile=dockerfile, tag=tag,
                                               decode=True, rm=True, pull=False, nocache=no_cache):
                if "error" in chunk:
                    raise BuildError(f"{tag}: {chunk['error'].strip()}")
        except docker.errors.DockerException as e:
            raise BuildError(f"{tag}: {e}") from None
        return self.image_id(tag)

    def image_id(self, tag: str) -> str:
        try:
            return self.client.images.get(tag).id
        except docker.errors.DockerException as e:
            raise BuildError(f"{tag}: {e}") from None

    def build_base(self, profile: BuildProfile, no_cache: Optional[bool] = None) -> str:
        return self._build(REPO_ROOT, profile.base_dockerfile, profile.base_image,
                           profile.no_cache if no_cache is None else no_cache)

    def build_execution_manager(self, profile: BuildProfile, no_cache: bool = False) -> Optional[str]:
        """Orchestration only. Built with the Docker cache, as compose built it before."""
        if not profile.needs_execution_manager:
            return None
        return self._build(REPO_ROOT, profile.execution_manager_dockerfile, profile.execution_manager_image, no_cache)

    def build_tasks(self, profile: BuildProfile, manifest: Manifest, no_cache: Optional[bool] = None) -> Dict[str, str]:
        """One image per manifest image, tagged with its name; returns {name: image ID}.

        Sources are relative to the manifest. Each image is built from the parent of its
        source folder, which the Dockerfile copies the task sources from."""
        here = Path(manifest.path).resolve().parent if manifest.path else Path.cwd()
        no_cache = profile.no_cache if no_cache is None else no_cache
        ids = {}
        for img in manifest.images:
            src = (here / img.src).resolve()
            if not src.is_dir():
                raise BuildError(f"image {img.name!r}: source folder {src} does not exist")
            context = src.parent
            dockerfile = src / f"Dockerfile.{img.name}"
            dockerfile.write_text(render_task_dockerfile(profile, src.name))
            try:
                ids[img.name] = self._build(context, os.path.relpath(dockerfile, context), img.name, no_cache)
            finally:
                dockerfile.unlink(missing_ok=True)
        return ids
