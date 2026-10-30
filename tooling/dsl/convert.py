"""
Converts a legacy manifest (the format before the DSL, `version: "1.0"`,
no `deployment` section) into a DSL 0.1 manifest.

A legacy manifest does not say how it is deployed, so the coordination and
technology are arguments. control_cpu defaults to 4, the core every runtime
hard-codes today; task_cpus defaults to the cores the tasks are pinned to.

    PYTHONPATH=tooling python3 -m dsl.convert legacy.yaml \\
        --coordination choreography --technology zeromq > manifest.yaml
"""

import argparse
import sys
from typing import Any, Dict, Iterable, List

import yaml

from .model import COMBINATIONS, SCHEMA_VERSION

DEFAULT_CONTROL_CPU = 4


def format_cpus(cpus: Iterable[int]) -> str:
    """[4, 5, 6, 7] -> '4-7'; [4, 6, 7] -> '4,6-7'."""
    cpus = sorted(set(cpus))
    parts: List[str] = []
    i = 0
    while i < len(cpus):
        j = i
        while j + 1 < len(cpus) and cpus[j + 1] == cpus[j] + 1:
            j += 1
        parts.append(str(cpus[i]) if i == j else f"{cpus[i]}-{cpus[j]}")
        i = j + 1
    return ",".join(parts)


def convert(legacy: Dict[str, Any], coordination: str, technology: str,
            control_cpu: int = DEFAULT_CONTROL_CPU, task_cpus: str = None) -> Dict[str, Any]:
    """Legacy manifest mapping -> DSL 0.1 manifest mapping (in the order it is written)."""
    if "deployment" in legacy:
        raise ValueError("this manifest already has a 'deployment' section")
    if (coordination, technology) not in COMBINATIONS:
        valid = ", ".join(f"{c}/{t}" for c, t in sorted(COMBINATIONS))
        raise ValueError(f"{coordination}/{technology} is not supported (valid: {valid})")

    images = legacy.get("images") or {}
    schedule = legacy.get("schedule") or {}
    tasks = schedule.get("tasks") or []

    deployment: Dict[str, Any] = {"coordination": coordination, "technology": technology}
    if images.get("repo"):
        deployment["registry"] = images["repo"]
    deployment["control_cpu"] = control_cpu
    deployment["task_cpus"] = task_cpus or format_cpus(t["cpu_affinity"] for t in tasks)

    new_tasks = []
    for t in tasks:
        new_tasks.append({
            "id": t["id"],
            "image": t["image"],
            "start": t["start"],
            "deadline": t["deadline"],
            "cpu_affinity": t["cpu_affinity"],
            "policy": str(t["policy"]).lower(),
            "priority": t["priority"],
            "depends_on": list(t.get("depends_on") or []),
            "inputs": {k: {"type": v["type"], "value": v["value"]} for k, v in (t.get("inputs") or {}).items()},
            "outputs": {k: {"type": v["type"]} for k, v in (t.get("outputs") or {}).items()},
        })

    return {
        "version": SCHEMA_VERSION,
        "deployment": deployment,
        "images": [{"name": i["alias"], "src": i["src"]} for i in images.get("tasks") or []],
        "schedule": {
            "name": schedule.get("name", "unnamed"),
            "description": schedule.get("description", ""),
            "iterations": schedule.get("iterations"),
            "time_unit": "ms",
            "tasks": new_tasks,
        },
    }


def dump(manifest: Dict[str, Any]) -> str:
    return yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False, width=100)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert a legacy manifest to DSL " + SCHEMA_VERSION)
    ap.add_argument("manifest", help="legacy manifest (YAML)")
    ap.add_argument("--coordination", required=True, choices=sorted({c for c, _ in COMBINATIONS}))
    ap.add_argument("--technology", required=True, choices=sorted({t for _, t in COMBINATIONS}))
    ap.add_argument("--control-cpu", type=int, default=DEFAULT_CONTROL_CPU,
                    help="core of the control threads (default: %(default)s)")
    ap.add_argument("--task-cpus", help='cores for task threads, e.g. "5-7" (default: the cores the tasks use)')
    ap.add_argument("-o", "--output", help="output file (default: standard output)")
    args = ap.parse_args(argv)

    with open(args.manifest) as f:
        legacy = yaml.safe_load(f)
    try:
        text = dump(convert(legacy, args.coordination, args.technology, args.control_cpu, args.task_cpus))
    except (ValueError, KeyError) as e:
        print(f"convert: {args.manifest}: {e}", file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
