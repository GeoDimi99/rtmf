"""
Rules between the fields of a manifest (plan section 04).

validate() never raises: it returns the errors (the manifest must be rejected)
and the warnings (the manifest is accepted, but probably not what was meant),
so `rtmo validate` can show all of them at once.
"""

from typing import List, Tuple

from .model import COMBINATIONS, SCHEMA_VERSION, Manifest

TIME_UNITS = {"ms", "us"}

# Accepted policy names and their priority ranges (task.h).
# 'normal' is another name for 'other' (SCHED_NORMAL), used by the *_nort scenarios.
PRIORITY_RANGES = {
    "fifo": (1, 99),
    "rr": (1, 99),
    "other": (-20, 19),
    "normal": (-20, 19),
}

# Input/output types the C runtimes can pass to a task.
VALUE_TYPES = {"int": int}


def validate(m: Manifest) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    d, s = m.deployment, m.schedule

    if m.version != SCHEMA_VERSION:
        errors.append(f"version: schema {m.version!r} is not supported by this RTMO (supported: {SCHEMA_VERSION!r})")

    # deployment
    if (d.coordination, d.technology) not in COMBINATIONS:
        valid = ", ".join(f"{c}/{t}" for c, t in sorted(COMBINATIONS))
        errors.append(f"deployment: {d.coordination}/{d.technology} is not supported (valid: {valid})")
    if d.control_cpu < 0:
        errors.append(f"deployment.control_cpu: {d.control_cpu} is not a core number")
    if not d.task_cpus:
        errors.append("deployment.task_cpus: no core given")
    elif d.control_cpu in d.task_cpus:
        warnings.append(f"deployment: control_cpu {d.control_cpu} is also in task_cpus: "
                        "tasks there share the core with the control threads")

    # images
    names = [i.name for i in m.images]
    if not names:
        errors.append("images: at least one image is required")
    for name in sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"images: name {name!r} is used more than once")
    for i in m.images:
        if not i.src:
            errors.append(f"images.{i.name}: empty src")

    # schedule
    if s.iterations < 1:
        errors.append(f"schedule.iterations: {s.iterations} (at least 1)")
    if s.time_unit not in TIME_UNITS:
        errors.append(f"schedule.time_unit: {s.time_unit!r} (valid: {', '.join(sorted(TIME_UNITS))})")
    if not s.tasks:
        errors.append("schedule.tasks: at least one task is required")

    ids = [t.id for t in s.tasks]
    for tid in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"schedule.tasks: id {tid} is used more than once")

    for t in s.tasks:
        w = f"task {t.id}"
        if t.id < 1:
            errors.append(f"{w}: id must be a positive integer")
        if t.image not in names:
            errors.append(f"{w}: image {t.image!r} is not declared in images")
        if not 0 <= t.start < t.deadline:
            errors.append(f"{w}: needs 0 <= start < deadline (start {t.start}, deadline {t.deadline})")
        if s.time_unit == "us":
            for name, value in (("start", t.start), ("deadline", t.deadline)):
                if value % 1000:
                    errors.append(f"{w}: {name} {value} us is not a whole number of ms "
                                  "(the runtimes schedule in ms)")
        if d.task_cpus and t.cpu_affinity not in d.task_cpus:
            errors.append(f"{w}: cpu_affinity {t.cpu_affinity} is not in task_cpus {d.task_cpus}")
        if t.policy not in PRIORITY_RANGES:
            errors.append(f"{w}: policy {t.policy!r} (valid: {', '.join(sorted(PRIORITY_RANGES))})")
        else:
            lo, hi = PRIORITY_RANGES[t.policy]
            if not lo <= t.priority <= hi:
                errors.append(f"{w}: priority {t.priority} outside {lo}..{hi} for policy {t.policy}")
        for name, inp in t.inputs.items():
            kind = VALUE_TYPES.get(inp.type)
            if kind is None:
                errors.append(f"{w}: input {name!r} has type {inp.type!r} (valid: {', '.join(VALUE_TYPES)})")
            elif isinstance(inp.value, bool) or not isinstance(inp.value, kind):
                errors.append(f"{w}: input {name!r} value {inp.value!r} is not of type {inp.type}")
        for name, typ in t.outputs.items():
            if typ not in VALUE_TYPES:
                errors.append(f"{w}: output {name!r} has type {typ!r} (valid: {', '.join(VALUE_TYPES)})")
        for dep in t.depends_on:
            if dep not in ids:
                errors.append(f"{w}: depends_on {dep!r} is not a task id")
            elif dep == t.id:
                errors.append(f"{w}: depends on itself")

    # depends_on cycles (only when every reference resolves)
    graph = {t.id: [x for x in t.depends_on if x in ids and x != t.id] for t in s.tasks}
    state = {}

    def visit(node, stack):
        state[node] = "open"
        for nxt in graph.get(node, []):
            if state.get(nxt) == "open":
                cycle = stack[stack.index(nxt):] + [nxt]
                errors.append("depends_on: cycle " + " -> ".join(str(x) for x in cycle))
            elif nxt not in state:
                visit(nxt, stack + [nxt])
        state[node] = "done"

    for tid in graph:
        if tid not in state:
            visit(tid, [tid])

    return errors, warnings
