"""
How each implementation's task-wrapper and execution-manager containers are run.

Every difference between the implementations' deploy-managers is declared
here once, as data, instead of in four copies of the runner. The values are
the ones the runtimes were measured with; changing one changes the numbers
(see the plan, section 05 and the open decisions on container settings).
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import docker

from dsl import Manifest
from dsl.convert import format_cpus
from encoders.orchestration_grpc import service_ports

# Host folder holding the gRPC Unix sockets, shared with the execution manager.
GRPC_IPC_HOST_DIR = "/tmp/rtmo-grpc-ipc"
GRPC_IPC_DIR = "/ipc"          # the same folder inside the containers
ZMQ_IPC_VOLUME = "zmq_ipc"     # named volume of the zeromq ipc:// endpoints

# Network of device/compose.yaml: Redis is reachable there as 'redis' (the name
# the mqueue and zeromq runtimes connect to); host-network containers reach it
# as 'localhost' through the published port.
DEVICE_NETWORK = "rtmo"


@dataclass
class RunProfile:
    name: str                                   # e.g. "choreography-zeromq"
    container_name: Callable[[str], str]        # image name -> container name
    network: Optional[str]                      # network of the task containers (None: Docker default)
    options: Callable[[Manifest, str], Dict]    # (manifest, image) -> containers.run() options
    readiness_socket: Optional[Callable[[Manifest, str], str]] = None   # (manifest, image) -> socket path
    execution_manager: Optional[Callable[[Manifest], Dict]] = None   # orchestration: name + containers.run() options
    reset_volumes: List[str] = field(default_factory=list)              # recreated before every apply


def cpu_environment(manifest: Manifest) -> Dict[str, str]:
    """Where the runtimes put their threads (runtime/common/include/rtmo_cpu.h)."""
    d = manifest.deployment
    return {"RTMO_CONTROL_CPU": str(d.control_cpu), "RTMO_TASK_CPUS": format_cpus(d.task_cpus)}


def task_cpuset(manifest: Manifest) -> str:
    """A task-wrapper container gets the control core and the task cores, nothing else."""
    d = manifest.deployment
    return format_cpus({d.control_cpu} | set(d.task_cpus))


def _base_options(manifest: Manifest, image: str, cap_add: List[str]) -> Dict:
    return {
        "cap_add": cap_add,
        "environment": {"TASK_NAME": image, "TASK_QUEUE_NAME": image, **cpu_environment(manifest)},
        "ulimits": [
            docker.types.Ulimit(name="rtprio", soft=99, hard=99),
            docker.types.Ulimit(name="memlock", soft=-1, hard=-1),
        ],
        "cpuset_cpus": task_cpuset(manifest),
    }


def _mqueue_options(manifest: Manifest, image: str) -> Dict:
    opts = _base_options(manifest, image, ["SYS_NICE", "IPC_LOCK"])
    opts.update(remove=False, ipc_mode="host")
    return opts


def _zeromq_options(manifest: Manifest, image: str) -> Dict:
    opts = _base_options(manifest, image, ["SYS_NICE", "IPC_LOCK"])
    opts.update(remove=False, volumes={ZMQ_IPC_VOLUME: {"bind": GRPC_IPC_DIR, "mode": "rw"}})
    return opts


def _grpc_options(manifest: Manifest, image: str) -> Dict:
    opts = _base_options(manifest, image, ["SYS_NICE"])
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


# Execution managers: the settings of the former per-implementation compose files, on the
# manifest's control core (the compose files fixed it to core 4).
def _em_orchestration_mqueue(manifest: Manifest) -> Dict:
    return {
        "name": "execution-manager",
        "ipc_mode": "host",
        "cpuset_cpus": str(manifest.deployment.control_cpu),
        "environment": cpu_environment(manifest),
        "cap_add": ["SYS_NICE", "IPC_LOCK"],
        "ulimits": [
            docker.types.Ulimit(name="rtprio", soft=99, hard=99),
            docker.types.Ulimit(name="memlock", soft=-1, hard=-1),
        ],
        "network": DEVICE_NETWORK,      # reads the plan from 'redis'
    }


def _em_orchestration_grpc(manifest: Manifest) -> Dict:
    return {
        "name": "execution-manager-grpc",
        "network_mode": "host",         # reads the plan from 'localhost'
        "cpuset_cpus": str(manifest.deployment.control_cpu),
        "environment": cpu_environment(manifest),
        "volumes": {GRPC_IPC_HOST_DIR: {"bind": GRPC_IPC_DIR, "mode": "rw"}},
        "cap_add": ["SYS_NICE"],
    }

PROFILES: Dict[str, RunProfile] = {
    # choreography wrappers read the plan from 'redis' on the device network
    "choreography-mqueue": RunProfile(
        name="choreography-mqueue", container_name=lambda image: image,
        network=DEVICE_NETWORK, options=_mqueue_options),
    "choreography-zeromq": RunProfile(
        name="choreography-zeromq", container_name=lambda image: image,
        network=DEVICE_NETWORK, options=_zeromq_options, reset_volumes=[ZMQ_IPC_VOLUME]),
    # orchestration-mqueue wrappers never talk to Redis: Docker's default network, as before
    "orchestration-mqueue": RunProfile(
        name="orchestration-mqueue", container_name=lambda image: image,
        network=None, options=_mqueue_options, execution_manager=_em_orchestration_mqueue),
    "orchestration-grpc": RunProfile(
        name="orchestration-grpc", container_name=lambda image: f"task-service-{image}",
        network=None, options=_grpc_options, readiness_socket=_grpc_socket,
        execution_manager=_em_orchestration_grpc),
}


def profile_for(manifest: Manifest) -> RunProfile:
    return PROFILES[manifest.deployment.profile]
