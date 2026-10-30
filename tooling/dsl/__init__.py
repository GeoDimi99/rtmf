"""RTMO manifest DSL: model, parser, validation and the legacy converter."""

from .model import COMBINATIONS, SCHEMA_VERSION, Deployment, Image, Input, Manifest, Schedule, Task
from .parser import LegacyManifestError, ManifestError, parse, parse_cpus
from .validation import validate


class InvalidManifestError(ManifestError):
    """The manifest is well formed but breaks validation rules."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def load(source):
    """Parse and validate a manifest; returns (manifest, warnings) or raises ManifestError."""
    manifest = parse(source)
    errors, warnings = validate(manifest)
    if errors:
        raise InvalidManifestError(errors)
    return manifest, warnings


__all__ = [
    "COMBINATIONS", "SCHEMA_VERSION", "Deployment", "Image", "Input", "Manifest", "Schedule", "Task",
    "ManifestError", "LegacyManifestError", "InvalidManifestError", "parse", "parse_cpus", "validate", "load",
]
