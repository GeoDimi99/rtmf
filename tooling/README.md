# tooling

Python side of RTMO. Run each component with this folder on `PYTHONPATH`, so both can
`import dsl`.

| Folder | What |
|---|---|
| `dsl/` | Manifest model, parser, validation rules (schema `0.1`) and the converter from legacy manifests. Shared by the builder and the deploy-manager. |
| `builder/` | Developer side: build profiles (what to build per coordination and technology) and the image builds. |
| `deploy-manager/` | Device side: run profiles (how to run the task-wrapper containers), the readiness check and the plan encoders that write the execution plan into Redis. |
| `tests/` | Unit tests, and tests showing the new code produces what the legacy deploy-managers produce. |
| `legacy/<impl>/` | The deploy-managers and image-builders the start scripts still use. Replaced by the code above when the command-line tools land (plan P4). |

The command-line tools (`rtmo validate | build | push`, `rtmod apply | status | stop`) come in P4.

## Convert a legacy manifest

A legacy manifest (`version: "1.0"`, no `deployment` section) does not say how it is deployed,
so the coordination and technology are arguments:

```bash
PYTHONPATH=tooling python3 -m dsl.convert benchmarks/scenarios/dual_core_sep.yaml \
    --coordination choreography --technology zeromq > dual_core_sep.yaml
```

`--control-cpu` (default 4) and `--task-cpus` (default: the cores the tasks use) set the CPU layout.

## Tests

Standard library `unittest`; they only need PyYAML and the `docker` module, no Docker daemon or Redis.

```bash
python3 -m unittest discover -s tooling/tests -v
```

The equivalence tests run on the two manifests in `tests/fixtures/` and, on the `benchmarks`
branch, on every scenario in `benchmarks/scenarios/`, for each of the four implementations:

- `test_encoders_match_legacy`: the Redis plan written by the new encoders equals the one the
  legacy loader writes, key by key. Only differences: the new `plan:format` key, and
  `schedule:images` (choreography), compared as a set because the legacy order came from a
  Python set; the new encoder writes it sorted.
- `test_run_profiles_match_legacy`: the task-wrapper containers are started with the same
  options as the legacy runners.
- `test_build_profiles_match_legacy`: the task images get the same Dockerfile instructions and
  base image as with the legacy image-builders.
