"""
Plan encoders: turn a manifest into the Redis data a runtime reads.

Each encoder reproduces the layout its C runtime expects today, key for key,
so the runtimes read exactly the plan they read before the DSL:

    orchestration_mqueue  `schedule` + `scheduletask:<i>`, keyed by task id/image
    orchestration_grpc    `schedule` + `scheduletask:<i>`, keyed by image, with service_port
    choreography          one flat hash `schedule_data`, grouped by image (mqueue and zeromq)

encode() is pure (manifest -> {key: {field: value}}); write() stores the result.
"""

from typing import Callable, Dict

from dsl import Manifest

from . import choreography, orchestration_grpc, orchestration_mqueue

Plan = Dict[str, Dict[str, str]]

# Written next to the plan so a runtime can check it reads the layout it expects.
PLAN_FORMAT_KEY = "plan:format"
PLAN_FORMAT_VERSION = "1"

ENCODERS: Dict[str, Callable[[Manifest], Plan]] = {
    "orchestration-mqueue": orchestration_mqueue.encode,
    "orchestration-grpc": orchestration_grpc.encode,
    "choreography-mqueue": choreography.encode,
    "choreography-zeromq": choreography.encode,
}


def encode(manifest: Manifest) -> Plan:
    return ENCODERS[manifest.deployment.profile](manifest)


def plan_format(manifest: Manifest) -> str:
    """e.g. 'choreography-zeromq/1'"""
    return f"{manifest.deployment.profile}/{PLAN_FORMAT_VERSION}"


def write(client, manifest: Manifest, plan: Plan = None) -> Plan:
    """Store the plan (and plan:format) through a redis-py client; returns the plan."""
    plan = encode(manifest) if plan is None else plan
    for key, mapping in plan.items():
        client.hset(key, mapping=mapping)
    client.set(PLAN_FORMAT_KEY, plan_format(manifest))
    return plan
