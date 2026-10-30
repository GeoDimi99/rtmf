"""
How each implementation's task-wrapper containers are run.

Every difference between the implementations' deploy-managers is declared
here once, as data, instead of in four copies of the runner. The values are
the ones the runtimes were measured with; changing one changes the numbers
(see the plan, section 05 and the open decisions on container settings).
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import docker

from dsl import Manifest
from encoders.orchestration_grpc import service_ports

# Host folder holding the gRPC Unix sockets, shared with the execution manager.
GRPC_IPC_HOST_DIR = "/tmp/rtmo-grpc-ipc"
GRPC_IPC_DIR = "/ipc"          # the same folder inside the containers
ZMQ_IPC_VOLUME = "zmq_ipc"     # named volume of the zeromq ipc:// endpoints


@dataclass
class RunProfile:
    name: str                                   # e.g. "choreography-zeromq"
    redis_host: str                             # where the deploy-manager reaches Redis
    container_name: Callable[[str], str]        # image name -> container name
    join_own_network: bool                      # run tasks on the deploy-manager's network
    options: Callable[[Manifest, str], Dict]    # (manifest, image) -> containers.run() options
    readiness_socket: Optional[Callable[[Manifest, str], str]] = None   # (manifest, image) -> socket path


def _base_options(image: str, cap_add: List[str]) -> Dict:
    return {
        "cap_add": cap_add,
        "environment": {"TASK_NAME": image, "TASK_QUEUE_NAME": image},
        "ulimits": [
            docker.types.Ulimit(name="rtprio", soft=99, hard=99),
            docker.types.Ulimit(name="memlock", soft=-1, hard=-1),
        ],
        "cpuset_cpus": "0-7",
    }


def _mqueue_options(manifest: Manifest, image: str) -> Dict:
    opts = _base_options(image, ["SYS_NICE", "IPC_LOCK"])
    opts.update(remove=False, ipc_mode="host")
    return opts


def _zeromq_options(manifest: Manifest, image: str) -> Dict:
    opts = _base_options(image, ["SYS_NICE", "IPC_LOCK"])
    opts.update(remove=False, volumes={ZMQ_IPC_VOLUME: {"bind": GRPC_IPC_DIR, "mode": "rw"}})
    return opts


def _grpc_options(manifest: Manifest, image: str) -> Dict:
    opts = _base_options(image, ["SYS_NICE"])
    opts["environment"]["GRPC_PORT"] = str(service_ports(manifest)[image])
    opts.update(
        tty=True,
        ipc_mode="host",
        network_mode="host",
        volumes={GRPC_IPC_HOST_DIR: {"bind": GRPC_IPC_DIR, "mode": "rw"}},
        tmpfs={"/tmp": "size=64m,mode=1777"},   # RAM-backed /tmp: see the plan's fairness note
    )
    return opts


def _grpc_socket(manifest: Manifest, image: str) -> str:
    return f"{GRPC_IPC_DIR}/task_{service_ports(manifest)[image]}.sock"


PROFILES: Dict[str, RunProfile] = {
    "choreography-mqueue": RunProfile(
        name="choreography-mqueue", redis_host="redis",
        container_name=lambda image: image, join_own_network=True, options=_mqueue_options),
    "choreography-zeromq": RunProfile(
        name="choreography-zeromq", redis_host="redis",
        container_name=lambda image: image, join_own_network=True, options=_zeromq_options),
    "orchestration-mqueue": RunProfile(
        name="orchestration-mqueue", redis_host="redis",
        container_name=lambda image: image, join_own_network=False, options=_mqueue_options),
    "orchestration-grpc": RunProfile(
        name="orchestration-grpc", redis_host="localhost",
        container_name=lambda image: f"task-service-{image}", join_own_network=False,
        options=_grpc_options, readiness_socket=_grpc_socket),
}


def profile_for(manifest: Manifest) -> RunProfile:
    return PROFILES[manifest.deployment.profile]
