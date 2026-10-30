"""
What the builder produces for each implementation.

Every implementation has a task-wrapper base image built from the local
checkout; each manifest image is that base plus the task sources, compiled
by the same template. Orchestration also needs an execution-manager image.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from dsl import Manifest


@dataclass
class BuildProfile:
    name: str                                # e.g. "orchestration-grpc"
    base_image: str                          # tag of the task-wrapper base image
    base_dockerfile: str                     # relative to the repository root
    entrypoint: str                          # binary the task image starts
    cmake_args: str = ""                     # extra arguments of the task build
    no_cache: bool = False                   # build the base and task images without the Docker cache
    execution_manager_dockerfile: Optional[str] = None   # orchestration only

    @property
    def execution_manager_image(self) -> str:
        return f"rtmo/execution-manager:{self.name}"

    @property
    def needs_execution_manager(self) -> bool:
        return self.execution_manager_dockerfile is not None


def _profile(name: str, entrypoint: str, **kw) -> BuildProfile:
    return BuildProfile(
        name=name,
        base_image=f"rtmo/task-wrapper:{name}",
        base_dockerfile=f"docker/{name}/task-wrapper.Dockerfile",
        entrypoint=entrypoint,
        **kw,
    )


PROFILES: Dict[str, BuildProfile] = {
    # choreography wrappers build a binary called execution-manager: each one
    # runs its own share of the schedule
    "choreography-mqueue": _profile("choreography-mqueue", "./build/execution-manager"),
    "choreography-zeromq": _profile("choreography-zeromq", "./build/execution-manager"),
    "orchestration-mqueue": _profile(
        "orchestration-mqueue", "./build/task-wrapper",
        execution_manager_dockerfile="docker/orchestration-mqueue/execution-manager.Dockerfile"),
    "orchestration-grpc": _profile(
        "orchestration-grpc", "./build/task-wrapper",
        cmake_args=" -DCMAKE_BUILD_TYPE=Debug", no_cache=True,
        execution_manager_dockerfile="docker/orchestration-grpc/execution-manager.Dockerfile"),
}


def profile_for(manifest: Manifest) -> BuildProfile:
    return PROFILES[manifest.deployment.profile]
