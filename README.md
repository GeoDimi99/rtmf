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
│   ├── common/shared/                #   logger and task model, same in every implementation
│   ├── common/<impl>/                #   task.h / task_ipc.* that still differ per implementation
│   ├── orchestration/execution-manager/{mqueue,grpc}/
│   ├── orchestration/task-wrapper/{mqueue,grpc}/
│   ├── choreography/task-wrapper/{mqueue,zeromq}/
│   ├── native/execution-manager/     #   bare-metal baseline (no Docker)
│   └── proto/task_service.proto      #   gRPC service definition
├── tooling/legacy/<impl>/            # Python: deploy-manager and image-builder per implementation
├── docker/<impl>/                    # Dockerfiles and compose.yaml (build context: repository root)
├── tests/
│   ├── manifests/                    #   benchmark scenarios
│   ├── tasks/<impl>/                 #   stress_task_1..6 and the default manifest.yaml
│   └── start-test/<impl>.sh          #   one test run of one implementation
├── tools/                            # perf_report.py, report-lib.sh, rt_vs_nonrt_ttest.py
├── docs/<impl>/                      # README and notes of each implementation
├── results/<impl>/<test>/            # test output (not in git)
└── run-all-tests.sh                  # whole campaign: every scenario on every implementation
```

`<impl>` is one of `orchestration-grpc`, `orchestration-mqueue`, `choreography-mqueue`,
`choreography-zeromq` and `native`. The layout is an intermediate step of the restructure:
the copies that still differ per implementation are merged in the next steps.

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

- **Image builder** (`tooling/legacy/<impl>/image-builder/`, runs on the developer machine): reads the manifest and
  builds one Docker image per task on top of the implementation's task-wrapper base image.
- **Deploy manager** (`tooling/legacy/<impl>/deploy-manager/`, container): reads the manifest, starts one
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

```bash
git clone https://github.com/GeoDimi99/rtmo.git
cd rtmo
tests/start-test/<impl>.sh [test-name]     # native: sudo tests/start-test/native.sh [test-name]
```

Each run writes `results/<impl>/<test-name>/` (a random `results/<impl>/test_<id>/` when no name is given) with
the container logs, a copy of the manifest, `perf.csv`, `stats.csv` and `report.pdf`.
Set `FORCE=1` to overwrite an existing results folder.

To compare a real-time run against non real-time runs of the same implementation:

```bash
python3 tools/rt_vs_nonrt_ttest.py --impl choreography-mqueue \
    --rt test_single_core_1 --nonrt test_single_core_nort_2
```

The CSV and PDF are written to `results/<implementation>/`.

---


<div align="center">

</div>
