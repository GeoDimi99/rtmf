"""
orchestration-grpc: `schedule` + `scheduletask:<i>` keyed by image, with the
service port of the task's container and the inputs with their types.
"""

import json
from typing import Dict

from dsl import Manifest

from .common import SCHEDULE_VERSION, to_ms

BASE_PORT = 50051


def service_ports(m: Manifest) -> Dict[str, int]:
    """One gRPC service per image, numbered in manifest order from BASE_PORT.
    The port only names the Unix socket of the service (/ipc/task_<port>.sock)."""
    return {img.name: BASE_PORT + n for n, img in enumerate(m.images)}


def encode(m: Manifest):
    s = m.schedule
    ports = service_ports(m)
    plan = {
        "schedule": {
            "name": s.name,
            "version": SCHEDULE_VERSION,
            "description": s.description,
            "length": str(len(s.tasks)),
            "iterations": str(s.iterations),
        }
    }
    for i, t in enumerate(s.tasks, start=1):
        plan[f"scheduletask:{i}"] = {
            "name": t.image,
            "policy": t.policy,
            "priority": str(t.priority),
            "depends_on": json.dumps(t.depends_on),
            "inputs": json.dumps({k: {"type": v.type, "value": v.value} for k, v in t.inputs.items()}),
            "outputs": json.dumps({k: {"type": typ} for k, typ in t.outputs.items()}),
            "cpu_affinity": str(t.cpu_affinity),
            "start": str(to_ms(m, t.start)),
            "deadline": str(to_ms(m, t.deadline)),
            "service_port": str(ports.get(t.image, BASE_PORT)),
        }
    return plan
