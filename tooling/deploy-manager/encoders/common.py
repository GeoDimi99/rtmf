"""Helpers shared by the encoders."""

from dsl import Manifest, Task

# The legacy loaders wrote the schedule-level `version` field, which no manifest
# ever set, so the runtimes always read its default. Kept for the same plan.
SCHEDULE_VERSION = "0.0.0"


def to_ms(manifest: Manifest, value: int) -> int:
    """Times in the plan are in ms; validation guarantees whole ms for time_unit 'us'."""
    return value // 1000 if manifest.schedule.time_unit == "us" else value


def input_values(task: Task):
    """Inputs as the mqueue/zeromq runtimes read them: a one-element list of {name: value}."""
    return [{name: inp.value for name, inp in task.inputs.items()}]


def output_types(task: Task):
    """Outputs as {name: type}."""
    return dict(task.outputs)
