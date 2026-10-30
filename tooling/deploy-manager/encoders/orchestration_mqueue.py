"""orchestration-mqueue: `schedule` + `scheduletask:<i>` (i from 1, in manifest order)."""

import json

from dsl import Manifest

from .common import SCHEDULE_VERSION, input_values, output_types, to_ms


def encode(m: Manifest):
    s = m.schedule
    plan = {
        "schedule": {
            "name": s.name,
            "version": SCHEDULE_VERSION,
            "description": s.description,
            "iterations": str(s.iterations),
            "length": str(len(s.tasks)),
        }
    }
    for i, t in enumerate(s.tasks, start=1):
        plan[f"scheduletask:{i}"] = {
            "id": str(t.id),
            "image": t.image,
            "start": str(to_ms(m, t.start)),
            "deadline": str(to_ms(m, t.deadline)),
            "cpu_affinity": str(t.cpu_affinity),
            "policy": t.policy,
            "priority": str(t.priority),
            "depends_on": json.dumps(t.depends_on),
            "inputs": json.dumps(input_values(t)),
            "outputs": json.dumps(output_types(t)),
        }
    return plan
