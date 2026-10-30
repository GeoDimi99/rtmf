<div align="center">

# RTMO - Real-Time Microservices Orchestration
### *A Framework for Automated Deployment and Coordination*

</div>

---

## What this repository contains

This repository hosts the **reference implementations** of the framework described in the paper.

---

## Repository layout

```
.
├── runtime/                          # C code
│   ├── common/                       #   logger and task model, shared by every implementation
│   ├── orchestration/execution-manager/{mqueue,grpc}/
│   ├── orchestration/task-wrapper/{mqueue,grpc}/
│   ├── orchestration/ipc/{mqueue,grpc}/   # task_ipc.h: message protocol of each implementation
│   ├── choreography/task-wrapper/{mqueue,zeromq}/
│   ├── choreography/ipc/{mqueue,zeromq}/
│   ├── native/execution-manager/     #   bare-metal baseline (no Docker)
│   └── proto/task_service.proto      #   gRPC service definition
├── tooling/                          # Python (see tooling/README.md)
│   ├── dsl/                          #   manifest model, validation, legacy converter
│   ├── builder/                      #   build profiles and image builds (developer side)
│   ├── deploy-manager/               #   run profiles and Redis plan encoders (device side)
│   └── tests/                        #   python3 -m unittest discover -s tooling/tests
├── docker/                           # deploy-manager.Dockerfile; <impl>/ task-wrapper and execution-manager
│                                     #   Dockerfiles (build context: repository root)
├── device/                           # compose.yaml (the device Redis), device.yaml.example
├── scripts/                          # lib.sh, launchers of rtmo and rtmod
├── tests/start-test/native.sh        # one run of the bare-metal baseline
├── tools/                            # run-test.sh, perf_report.py, report-lib.sh, rt_vs_nonrt_ttest.py
├── docs/<impl>/                      # README and notes of each implementation
├── results/<impl>/<test>/            # test output (not in git)
├── install.sh, VERSION
└── benchmarks/                       # only on the benchmarks branch: the application
    ├── tasks/stress_task_1..6/       #   task sources, one copy for every implementation
    ├── scenarios/                    #   13 benchmark scenarios (DSL 0.1)
    ├── golden/                       #   what the former tooling produced, for the tests
    └── run-campaign.sh               #   whole campaign: every scenario on every implementation
```

`<impl>` is one of `orchestration-grpc`, `orchestration-mqueue`, `choreography-mqueue`,
`choreography-zeromq` and `native`. The framework lives on `main`; the benchmark application
(tasks, scenarios, campaign script) lives on the `benchmarks` branch, which is `main` plus the
`benchmarks/` folder. The start scripts need the `benchmarks/` folder, so tests run from the
`benchmarks` branch.

---

## The architectures

| Project | Pattern | IPC between containers | Containers |
|---|---|---|---|
| [`orchestration-grpc`](docs/orchestration-grpc/README.md) | Orchestration | gRPC (host network, one port per task image) | redis, deploy-manager, execution-manager, one task-wrapper per image |
| [`orchestration-mqueue`](docs/orchestration-mqueue/README.md) | Orchestration | POSIX message queues (`ipc: host`) | redis, deploy-manager, execution-manager, one task-wrapper per image |
| [`choreography-mqueue`](docs/choreography-mqueue/README.md) | Choreography | POSIX message queues (`ipc: host`) | redis, deploy-manager, one task-wrapper per image |
| [`choreography-zeromq`](docs/choreography-zeromq/README.md) | Choreography | ZeroMQ over Unix sockets (shared `zmq_ipc` volume) | redis, deploy-manager, one task-wrapper per image |
| [`native`](docs/native/README.md) | Single host process, multi-threaded | none | none (runs on the host) |

The four containerised implementations share the same building blocks:

- **Image builder** (`rtmo build`, `tooling/builder/`, runs on the developer machine): reads the manifest and
  builds one Docker image per task on top of the implementation's task-wrapper base image.
- **Deploy manager** (`rtmod apply`, `tooling/deploy-manager/`, container): reads the manifest, starts one
  task-wrapper container per task image and writes the execution plan into **Redis**.
- **Orchestration**: a central **execution manager** reads the plan from Redis and triggers the
  task-wrappers (workers).
- **Choreography**: there is no central execution manager. Every task-wrapper reads its own part
  of the plan from Redis, joins a start barrier with the other containers and runs its own timeline.

The manifest format (`images` + `schedule` sections) and the task API (`app_task.h` /
`app_task.c`) are the same in all four containerised implementations, so the same task sources
can be used by all of them. The Redis layout of the execution plan is implementation-specific
(see each implementation's README in `docs/<impl>/`).

---

## Common prerequisites

Every sub-project needs:

- **Linux host with `PREEMPT_RT` kernel**: `SCHED_FIFO`, `mlockall`, `SYS_NICE`, POSIX mqueue and Unix
  sockets.
- **Docker Engine ≥ 20.10** with Docker Compose v2 (`docker compose ...`), not needed by `native/`.
- **Python ≥ 3.10** with access to `/var/run/docker.sock`.
- The image-builder Python deps:

  ```bash
  pip install pyyaml python-dotenv docker
  ```

The report scripts (`tools/perf_report.py`) need `matplotlib`, `numpy` and `PyYAML`; the start
scripts install them into `tools/.venv` when they are missing.

---

## Running a test

Install once, from a clone, on the machine that builds (developer) and on the one that runs
(device); one machine can do both:

```bash
git clone https://github.com/GeoDimi99/rtmo.git && cd rtmo
sudo ./install.sh --role developer --role device   # rtmo, rtmod, deploy-manager image, Redis
./install.sh --role developer --check              # only check the prerequisites
```

Then, with a manifest (schema 0.1, see `tooling/README.md` to convert a legacy one):

```bash
rtmo validate my_app.yaml
rtmo build    my_app.yaml                # images + lock file in .rtmo/ next to the manifest
rtmod apply   my_app.yaml                # containers + plan in Redis (+ execution manager)
rtmod status
rtmod stop
```

`tools/run-test.sh <manifest> [test-name]` does a whole measured run: build, apply, follow
until the run ends, collect the logs, stop, and write `results/<impl>/<test-name>/` (logs,
`manifest.yaml`, `perf.csv`, `stats.csv`, `report.pdf`). Every command takes
`--coordination`, `--technology` and `--iterations` to override the manifest.

The benchmark campaign lives on the `benchmarks` branch:

```bash
git switch benchmarks
sudo benchmarks/run-campaign.sh          # every scenario on every implementation
```

`native` keeps its own script: `sudo tests/start-test/native.sh [test-name]`.

To compare a real-time run against non real-time runs of the same implementation:

```bash
python3 tools/rt_vs_nonrt_ttest.py --impl choreography-mqueue \
    --rt test_single_core_1 --nonrt test_single_core_nort_2
```

The CSV and PDF are written to `results/<implementation>/`.

---


<div align="center">

</div>
