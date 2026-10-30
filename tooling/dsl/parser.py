"""
Reads a manifest (YAML file or already-loaded mapping) into the model.

Only the structure is checked here: required fields, field types, CPU lists.
The rules between fields (valid combinations, timing, priorities, ...) are in
validation.py.
"""

from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from .model import Deployment, Image, Input, Manifest, Schedule, Task


class ManifestError(Exception):
    """The manifest cannot be read or does not have the expected structure."""


class LegacyManifestError(ManifestError):
    """A manifest in the format used before the DSL (no `deployment` section)."""


def parse_cpus(value: Any, where: str) -> List[int]:
    """'5-7' -> [5, 6, 7]; '4,6-7' -> [4, 6, 7]; 4 -> [4]."""
    if isinstance(value, bool):
        raise ManifestError(f"{where}: expected a core number or a list like \"5-7\", got {value!r}")
    if isinstance(value, int):
        return [value]
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where}: expected a core number or a list like \"5-7\", got {value!r}")
    cpus: List[int] = []
    for part in value.split(","):
        part = part.strip()
        try:
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-", 1))
                if lo > hi:
                    raise ValueError
                cpus.extend(range(lo, hi + 1))
            else:
                cpus.append(int(part))
        except ValueError:
            raise ManifestError(f"{where}: invalid core list {value!r}") from None
    return sorted(set(cpus))


def _require(data: Dict[str, Any], key: str, kind, where: str):
    if not isinstance(data, dict):
        raise ManifestError(f"{where}: expected a mapping")
    if key not in data:
        raise ManifestError(f"{where}: missing required field '{key}'")
    value = data[key]
    kinds = kind if isinstance(kind, tuple) else (kind,)
    # bool is an int in Python; never accept it where a number is expected
    if isinstance(value, bool) and bool not in kinds:
        raise ManifestError(f"{where}.{key}: expected {kinds[0].__name__}, got {value!r}")
    if not isinstance(value, kinds):
        raise ManifestError(f"{where}.{key}: expected {kinds[0].__name__}, got {value!r}")
    return value


def _parse_task(t: Dict[str, Any], where: str) -> Task:
    inputs: Dict[str, Input] = {}
    for name, spec in (_require(t, "inputs", dict, where) or {}).items():
        w = f"{where}.inputs.{name}"
        inputs[name] = Input(type=_require(spec, "type", str, w), value=_require(spec, "value", object, w))
    outputs: Dict[str, str] = {}
    for name, spec in (_require(t, "outputs", dict, where) or {}).items():
        outputs[name] = _require(spec, "type", str, f"{where}.outputs.{name}")
    return Task(
        id=_require(t, "id", int, where),
        image=_require(t, "image", str, where),
        start=_require(t, "start", int, where),
        deadline=_require(t, "deadline", int, where),
        cpu_affinity=_require(t, "cpu_affinity", int, where),
        policy=_require(t, "policy", str, where).lower(),
        priority=_require(t, "priority", int, where),
        depends_on=list(_require(t, "depends_on", list, where)),
        inputs=inputs,
        outputs=outputs,
    )


def parse(source: Union[str, Path, Dict[str, Any]]) -> Manifest:
    """Read a manifest from a file path or a mapping."""
    path = None
    if isinstance(source, (str, Path)):
        path = str(source)
        try:
            with open(source) as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            raise ManifestError(f"manifest not found: {source}") from None
        except yaml.YAMLError as e:
            raise ManifestError(f"{source}: invalid YAML: {e}") from None
    else:
        data = source
    if not isinstance(data, dict):
        raise ManifestError("manifest: expected a mapping at the top level")

    if "deployment" not in data:
        raise LegacyManifestError(
            "manifest has no 'deployment' section: it is a legacy manifest "
            "(convert it with: python -m dsl.convert <manifest> --coordination ... --technology ...)")

    version = _require(data, "version", (str, int, float), "manifest")

    d = _require(data, "deployment", dict, "manifest")
    deployment = Deployment(
        coordination=_require(d, "coordination", str, "deployment"),
        technology=_require(d, "technology", str, "deployment"),
        control_cpu=_require(d, "control_cpu", int, "deployment"),
        task_cpus=parse_cpus(_require(d, "task_cpus", (str, int), "deployment"), "deployment.task_cpus"),
        registry=d.get("registry") or "",
    )

    images: List[Image] = []
    for n, img in enumerate(_require(data, "images", list, "manifest")):
        where = f"images[{n}]"
        images.append(Image(name=_require(img, "name", str, where), src=_require(img, "src", str, where)))

    s = _require(data, "schedule", dict, "manifest")
    tasks = [_parse_task(t, f"schedule.tasks[{n}]")
             for n, t in enumerate(_require(s, "tasks", list, "schedule"))]
    schedule = Schedule(
        name=_require(s, "name", str, "schedule"),
        description=_require(s, "description", str, "schedule"),
        iterations=_require(s, "iterations", int, "schedule"),
        time_unit=_require(s, "time_unit", str, "schedule"),
        tasks=tasks,
    )
    return Manifest(version=str(version), deployment=deployment, images=images, schedule=schedule, path=path)
