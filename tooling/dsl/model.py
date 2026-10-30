"""
Manifest model of the RTMO DSL (schema version 0.1).

The dataclasses mirror the three sections of a manifest: `deployment` (how and
where the application runs), `images` (what to build) and `schedule` (what to
run, and when). They hold the manifest as written; checks live in
validation.py, conversion to a Redis plan in the deploy-manager encoders.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "0.1"

# (coordination, technology) pairs the runtimes implement.
COMBINATIONS = {
    ("orchestration", "grpc"),
    ("orchestration", "mqueue"),
    ("choreography", "mqueue"),
    ("choreography", "zeromq"),
}


@dataclass
class Deployment:
    coordination: str          # orchestration | choreography
    technology: str            # grpc | mqueue | zeromq
    control_cpu: int           # execution manager + wrapper control threads
    task_cpus: List[int]       # cores task threads may use ("5-7" in the manifest)
    registry: str = ""         # optional image registry

    @property
    def profile(self) -> str:
        """Implementation name, e.g. 'choreography-zeromq'."""
        return f"{self.coordination}-{self.technology}"


@dataclass
class Image:
    name: str
    src: str                   # source folder, relative to the manifest's directory


@dataclass
class Input:
    type: str
    value: Any


@dataclass
class Task:
    id: int
    image: str
    start: int
    deadline: int
    cpu_affinity: int
    policy: str
    priority: int
    depends_on: List[int] = field(default_factory=list)
    inputs: Dict[str, Input] = field(default_factory=dict)     # in manifest order
    outputs: Dict[str, str] = field(default_factory=dict)      # name -> type


@dataclass
class Schedule:
    name: str
    description: str
    iterations: int
    time_unit: str             # ms | us
    tasks: List[Task] = field(default_factory=list)


@dataclass
class Manifest:
    version: str
    deployment: Deployment
    images: List[Image]
    schedule: Schedule
    path: Optional[str] = None  # file the manifest was read from

    def image(self, name: str) -> Optional[Image]:
        return next((i for i in self.images if i.name == name), None)
