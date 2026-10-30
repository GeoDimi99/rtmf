# tooling

Python side of RTMO. Run each component with this folder on `PYTHONPATH`, so both can
`import dsl`.

| Folder | What |
|---|---|
| `dsl/` | Manifest model, parser, validation rules (schema `0.1`) and the converter from legacy manifests. Shared by the builder and the deploy-manager. |
| `builder/` | Developer side, command `rtmo` (`main.py`): validate, build (images + lock file), push. Build profiles per coordination and technology. |
| `deploy-manager/` | Device side, command `rtmod` (`main.py`, runs in the deploy-manager image): apply, status, stop. Run profiles (how to run the task-wrapper and execution-manager containers), readiness check, plan encoders, applied state in Redis. |
| `tests/` | Unit tests, and tests showing the new code produces what the legacy deploy-managers produce. |
| `legacy/<impl>/` | The former deploy-managers and image-builders, still used by `tests/start-test/<impl>.sh`; removed once the new path is confirmed. |

Install the commands with `install.sh` (see the repository README).

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

The reference is what the legacy tooling produced, recorded once by `record_golden.py`
into `tests/golden/` (fixtures) and `benchmarks/golden/` (scenarios):

- `test_encoders_match_golden`: the Redis plan written by the new encoders equals the legacy
  one, key by key. Only differences: the new `plan:format` key, and `schedule:images`
  (choreography), compared as a set because the legacy order came from a Python set; the new
  encoder writes it sorted.
- `test_run_profiles_match_golden`: task-wrapper and execution-manager containers get the
  legacy options; only additions are the `rtmo.*` labels and, for choreography and the
  orchestration-mqueue execution manager, the device network `rtmo`.
- `test_build_profiles_match_golden`: task images get the legacy Dockerfile instructions,
  base image and cache use.
- `test_apply`, `test_rtmo_cli`, `test_dsl`: apply steps and checks, the `rtmo` command and
  lock file, the DSL rules.
