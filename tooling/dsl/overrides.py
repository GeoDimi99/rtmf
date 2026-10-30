"""
Command-line overrides of a manifest, so one scenario can run on every
implementation (plan section 04: the CLI can override coordination and
technology for benchmark campaigns), and with another iteration count.
"""

import copy
from typing import Any, Dict, Optional

import yaml

from .parser import ManifestError


def read(path: str) -> Dict[str, Any]:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ManifestError(f"manifest not found: {path}") from None
    except yaml.YAMLError as e:
        raise ManifestError(f"{path}: invalid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: expected a mapping at the top level")
    return data


def override(data: Dict[str, Any], coordination: Optional[str] = None, technology: Optional[str] = None,
             iterations: Optional[int] = None) -> Dict[str, Any]:
    """A copy of the manifest mapping with the given fields replaced."""
    data = copy.deepcopy(data)
    if coordination is not None or technology is not None:
        dep = data.setdefault("deployment", {})
        if not isinstance(dep, dict):
            raise ManifestError("deployment: expected a mapping")
        if coordination is not None:
            dep["coordination"] = coordination
        if technology is not None:
            dep["technology"] = technology
    if iterations is not None:
        sched = data.get("schedule")
        if not isinstance(sched, dict):
            raise ManifestError("schedule: expected a mapping")
        sched["iterations"] = iterations
    return data


def add_arguments(parser) -> None:
    """The override options shared by rtmo and rtmod."""
    parser.add_argument("--coordination", help="override deployment.coordination")
    parser.add_argument("--technology", help="override deployment.technology")
    parser.add_argument("--iterations", type=int, help="override schedule.iterations")


def from_arguments(args) -> Dict[str, Any]:
    return {"coordination": args.coordination, "technology": args.technology, "iterations": args.iterations}
