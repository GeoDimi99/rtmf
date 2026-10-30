"""
choreography (mqueue and zeromq): one flat hash `schedule_data`.

Every wrapper reads the whole hash, keeps its own tasks (`schedule:<image>:<n>`)
and uses `schedule:images` as the peer list of the start barrier. The leader is
the image of the earliest task; it broadcasts time zero.
"""

import json

from dsl import Manifest

from .common import SCHEDULE_VERSION, input_values, output_types, to_ms

KEY = "schedule_data"


def encode(m: Manifest):
    s = m.schedule
    tasks_by_image = {}
    for t in s.tasks:
        tasks_by_image.setdefault(t.image, []).append(t)

    # Leader: image of the first task with the earliest start (manifest order on ties).
    leader = min(s.tasks, key=lambda t: t.start).image if s.tasks else ""
    duration = max([0] + [to_ms(m, t.deadline) for t in s.tasks])

    data = {
        "schedule:name": s.name,
        "schedule:version": SCHEDULE_VERSION,
        "schedule:description": s.description,
        "schedule:length": str(len(tasks_by_image)),
        "schedule:duration": str(duration),
        # Sorted: the legacy loader wrote list(set(...)), whose order changed from run to run.
        "schedule:images": json.dumps(sorted(tasks_by_image)),
        "schedule:leader": leader,
        "schedule:iterations": str(s.iterations),
    }
    for image, tasks in tasks_by_image.items():
        data[f"schedule:{image}:length"] = str(len(tasks))
        for n, t in enumerate(tasks):
            data[f"schedule:{image}:{n}"] = json.dumps({
                "id": t.id,
                "start": to_ms(m, t.start),
                "deadline": to_ms(m, t.deadline),
                "cpu_affinity": str(t.cpu_affinity),
                "policy": t.policy,
                "priority": str(t.priority),
                "depends_on": json.dumps(t.depends_on),
                "inputs": json.dumps(input_values(t)),
                "outputs": json.dumps(output_types(t)),
            })
    return {KEY: data}
