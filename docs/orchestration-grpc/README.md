<div align="center">

# ⚡ Orchestration Microservices gRPC
</div>

---

Orchestration pattern of RTMO: a central **execution-manager** reads the schedule from Redis
and dispatches each task to its **task-wrapper** container through gRPC. The **deploy-manager**
starts one task-wrapper container per task image and loads the schedule into Redis.

## 📁 Repository layout

Paths from the root of the RTMO repository:

```
runtime/common/                                    # logger, task model (same in every implementation)
runtime/orchestration/ipc/grpc/                    # task_ipc.h: message protocol of this implementation
runtime/orchestration/execution-manager/grpc/      # C/C++: central execution manager (gRPC client)
runtime/orchestration/task-wrapper/grpc/           # C/C++: task-wrapper base image (gRPC server)
runtime/proto/task_service.proto                   # gRPC service definition
tooling/legacy/orchestration-grpc/image-builder/   # Python CLI that builds per-task Docker images
tooling/legacy/orchestration-grpc/deploy-manager/  # Python: spawns task containers + writes Redis
docker/orchestration-grpc/                         # Dockerfiles + compose.yaml
benchmarks/tasks/orchestration-grpc.yaml           # default manifest (benchmarks branch)
benchmarks/tasks/stress_task_*/                    # task sources, shared by every implementation (benchmarks branch)
tests/start-test/orchestration-grpc.sh             # end-to-end build, run & benchmark
tools/                                             # performance report scripts
results/orchestration-grpc/                        # one folder per test run (logs, perf.csv, stats.csv, report.pdf)
docs/orchestration-grpc/                           # this README and notes
```

---

## ⚙️ How it works

1. **deploy-manager** (host network) parses the manifest and assigns one gRPC port to each entry of
   `images.tasks`, in order: `50051`, `50052`, ... For every image it starts a container named
   `task-service-<alias>` (`network_mode=host`, `ipc_mode=host`, `cap_add=[SYS_NICE]`,
   `rtprio=99`, `memlock=unlimited`, `cpuset 0-7`, RAM-backed `/tmp`, env `TASK_NAME`, `GRPC_PORT`)
   and waits until its gRPC server accepts connections on the Unix socket `/ipc/task_<port>.sock`.
   gRPC runs over Unix domain sockets (host directory `/tmp/rtmo-grpc-ipc`, mounted as `/ipc` in
   the task services, deploy-manager and execution-manager), like the `ipc://` endpoints of
   choreography-zeromq: on the PREEMPT_RT kernel loopback TCP is received by `ksoftirqd`
   (SCHED_OTHER), so a task computing on core 4 delayed every request and result until it ended.
2. It then writes the schedule into Redis (`localhost:6379`):
   - hash `schedule`: `name`, `version`, `description`, `length`, `iterations`
   - hash `scheduletask:<i>` (i = 1..length, the position of the task in `schedule.tasks`):
     `name` (image alias), `policy`, `priority`, `cpu_affinity`, `start`, `deadline`,
     `depends_on`, `inputs`, `outputs`, `service_port`
3. **execution-manager** (container `execution-manager-grpc`, SCHED_FIFO 90, CPU 4) reads the
   schedule from Redis **once at start-up**, so it must be started after the deploy-manager has
   finished. It fires every task at its `start` time with a gRPC call to `unix:///ipc/task_<service_port>.sock`
   and aborts the call when the task exceeds its `deadline`.
4. The task-wrapper runs `task_main()` in a thread with the requested policy/priority/affinity and
   returns the result in the gRPC response.

Several schedule tasks may use the same image: they are all served by the same container.

---


## 📋 Prerequisites

- **Linux host with `PREEMPT_RT` kernel** (host networking + `SYS_NICE` are Linux-only).
- **Docker Engine ≥ 20.10** with Docker Compose v2 (the `docker compose ...` syntax).
- **Python ≥ 3.10** and access to `/var/run/docker.sock`.
- Python packages used by the image-builder (declared in `tooling/legacy/orchestration-grpc/image-builder/requirements.txt`):

  ```bash
  pip install -r tooling/legacy/orchestration-grpc/image-builder/requirements.txt
  ```

> **Tip.** If you don't want to install the Python deps system-wide, use a virtualenv: `python3 -m venv .venv && source .venv/bin/activate && pip install -r tooling/legacy/orchestration-grpc/image-builder/requirements.txt`.

---

## 🚀 Automated start

```bash
git clone https://github.com/GeoDimi99/RTMO.git
cd RTMO/orchestration-grpc
tests/start-test/orchestration-grpc.sh [test-name]
```

`start-test.sh` builds every image (with `--no-cache`), starts Redis, runs the deploy-manager,
then runs the execution-manager in the foreground, saves the logs (the execution-manager log is
saved as `execution-manager.log`) and generates the performance report in `results/orchestration-grpc/<test-name>/` (a random `results/orchestration-grpc/test_<id>/` when no name is given).

| Variable | Meaning |
|---|---|
| `MANIFEST=<path>` | Manifest to run (default: `benchmarks/tasks/orchestration-grpc.yaml`). A custom one is **copied over** `benchmarks/tasks/orchestration-grpc.yaml` (the original file is overwritten), so that the image-builder and the deploy-manager use the same manifest. |
| `FORCE=1` | Overwrite `results/orchestration-grpc/<test-name>/` if it already exists. |

---

## 🛠️ Manual workflow

Follow these instructions to start the system step by step:

```bash
# 1. Build the task-wrapper base image (tag must match images.base in the manifest)
docker build -t rtmo/task-wrapper:orchestration-grpc \
    -f runtime/orchestration/task-wrapper/grpc/Dockerfile .

# 2. Build all per-task images from the manifest
python3 tooling/legacy/orchestration-grpc/image-builder/src/main.py -f benchmarks/tasks/orchestration-grpc.yaml -c benchmarks/tasks

# 3. Build the orchestrators
docker compose build deploy-manager execution-manager

# 4. Start Redis
docker compose up -d redis

# 5. Deploy task-services and populate Redis
docker compose up deploy-manager

# 6. Execute the schedule (only after step 5 has finished: it reads Redis once)
docker compose up execution-manager

# 7. Cleanup
docker compose down
docker rm -f $(docker ps -aq --filter "name=task-service-") 2>/dev/null || true
```

> Add `--no-cache` to the image-builder or `docker compose build --no-cache` to force a clean rebuild.

> **Note.** The manifest is copied into the deploy-manager image at build time
> (`/app/tests/test_0_code/manifest.yaml`). After editing the manifest, rebuild the
> deploy-manager (step 3) as well as the task images (step 2).

---

## 📝 Manifest reference

A manifest has two top-level sections:

- **`images`** — base image, optional remote repo, list of task images to build.
- **`schedule`** — list of tasks with their real-time parameters.

### Minimal example

```yaml
version: "1.0"

images:
  base: "rtmo/task-wrapper:orchestration-grpc"
  repo: "jeffadac/realtime-microservices"
  tasks:
    - alias: "stress_task_1"
      src:   "stress_task_1"

schedule:
  name: "Single-task demo"
  description: "One configurable CPU/IO stress task."
  iterations: 10

  tasks:
    - id: 1
      image: "stress_task_1"
      start: 50            # ms after schedule t₀
      deadline: 650        # ms after schedule t₀ (absolute)
      cpu_affinity: 5      # pin worker thread to CPU 5
      policy: "fifo"       # fifo | rr | other | normal | batch | idle
      priority: 50         # RT priority [1..99] for fifo/rr, nice value otherwise
      depends_on: []
      inputs:
        total_ops:     { type: int, value: 17 }
        io_percentage: { type: int, value: 0  }
      outputs:
        result:        { type: int }
```

### Field semantics

| Field | Type | Meaning |
|---|---|---|
| `images.base` | string | Base image used by every task image. Must match the tag built in step 1. |
| `images.repo` | string | Optional Docker repo for tagging/pushing (publishing is currently disabled). |
| `images.tasks[].alias` | string | Local name of the image (matches `schedule.tasks[].image`). The container is `task-service-<alias>`. |
| `images.tasks[].src` | string | Sub-folder under the build context containing `app_task.h` and `app_task.c`. |
| `schedule.name` / `description` / `version` | string | Descriptive metadata (`version` defaults to `0.0.0`). |
| `schedule.iterations` | int | How many times the whole schedule is replayed back-to-back (default `1`, values `< 1` run it once). |
| `schedule.tasks[].id` | int | **Not read** by this implementation: tasks are numbered by their position in `schedule.tasks` (1, 2, ...), and that number is the `task_id` in logs, Redis and `perf.csv`. Keep `id` equal to the position for consistency with the other implementations. |
| `schedule.tasks[].image` | string | Image alias the task runs in. Must be declared under `images.tasks`. Several tasks may share the same image. **Required.** |
| `schedule.tasks[].start` | int (ms) | Time after t₀ when the task is fired. |
| `schedule.tasks[].deadline` | int (ms) | Absolute deadline (after t₀). The execution manager cancels the RPC if exceeded. |
| `schedule.tasks[].policy` | enum | `fifo` → `SCHED_FIFO`, `rr` → `SCHED_RR`, `other`/`normal` → `SCHED_OTHER`, `batch` → `SCHED_BATCH`, `idle` → `SCHED_IDLE`. `deadline` is accepted but not supported yet (it needs `sched_setattr`). Default: `fifo`. |
| `schedule.tasks[].priority` | int | RT priority `1..99` for `fifo`/`rr`; nice value `-20..19` for `other`/`normal`/`batch`; ignored for `idle`. Default: `50`. |
| `schedule.tasks[].cpu_affinity` | int | CPU index the worker thread is pinned to (optional). |
| `schedule.tasks[].depends_on` | list | Reserved for future DAG support: stored in Redis but ignored by the execution-manager. |
| `schedule.tasks[].inputs` | map | Typed inputs; the `value`s are passed to the task as a JSON object (`{"total_ops": 17, ...}`). |
| `schedule.tasks[].outputs` | map | Declared output schema (informative). |


### Task API

A task is two files, `app_task.h` and `app_task.c`. The API is the same in every containerised
RTMO implementation, so the same task sources can be used by all of them:

```c
/* app_task.h */
typedef struct { int total_ops; int io_percentage; } input_t;   /* task-specific */
typedef struct { int result; } output_t;                         /* task-specific */

int    convert_json_to_input(JsonObject *obj, input_t *input);   /* JSON inputs -> input_t */
gchar *convert_output_to_json(const output_t *output);           /* output_t -> JSON (g_free'd by the wrapper) */
void  *task_main(void *arg);   /* arg is an input_t*; returns a g_new0-allocated output_t* (g_free'd by the wrapper) */
```

The task-wrapper (`runtime/orchestration/task-wrapper/grpc/src/grpc_server.cpp`) parses the request, runs
`task_main()` in a thread with the requested policy/priority/affinity and sends back the result.


### Adding a new task

1. Create `benchmarks/tasks/my_task/` with `app_task.h` and `app_task.c` (see `benchmarks/tasks/stress_task_1/` for a template).
2. Add the alias under `images.tasks` in the manifest.
3. Add one or more entries under `schedule.tasks` referencing that alias.
4. Re-run `tests/start-test/orchestration-grpc.sh` (or steps 2–6 of the manual workflow).


---



## 🖥️ Sample output

Excerpt of a run with the default manifest (6 tasks, 100 iterations):

```text
deploy-manager          | [INFO] deploy-manager: Parsed schedule 'Configurable CPU/IO Benchmark' with 6 tasks.
deploy-manager          | [INFO] deploy-manager: Found 6 task image(s) for 6 task(s)
deploy-manager          | [INFO] deploy-manager: Deploying container for image 'stress_task_1' on port 50051
deploy-manager          | [INFO] deploy-manager: Running container 'task-service-stress_task_1' from image 'stress_task_1'
deploy-manager          | [INFO] deploy-manager: gRPC server at unix:///ipc/task_50051.sock is ready!
...
deploy-manager          | [INFO] deploy-manager: Schedule data loaded into Redis successfully.

execution-manager-grpc  | [INFO] execution-manager: Execution Manager running with SCHED_FIFO priority 90
execution-manager-grpc  | [INFO] execution-manager: Reading schedule from Redis...
execution-manager-grpc  | [INFO] execution-manager: Redis data: schedule Configurable CPU/IO Benchmark (v0.0.0), 6 task(s), 100 iteration(s)
execution-manager-grpc  | [INFO] execution-manager: Real-time event-driven scheduler starting
execution-manager-grpc  | [PERF] execution-manager: iteration=0 task_id=1 ... q_em_tw_ms=4.637 t_in_tw_ms=86.794 q_tw_em_ms=0.612 total_ms=92.043 core_id=4
...
execution-manager-grpc  | [INFO] execution-manager: All 100 iteration(s) completed
execution-manager-grpc  | [INFO] execution-manager: Test suite finished successfully
```

---

## 🧰 Useful commands

```bash
# Inspect Redis content
docker exec -it redis redis-cli
> KEYS *
> HGETALL schedule
> HGETALL scheduletask:1

# Tail logs
docker logs -f deploy-manager
docker logs -f execution-manager-grpc
docker logs -f task-service-stress_task_1

# List task-services
docker ps --filter "name=task-service-"

# Full cleanup
docker compose down -v
docker rm -f $(docker ps -aq --filter "name=task-service-") 2>/dev/null || true
```

---

## ❗ Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `protoc: command not found` during build | Stale execution-manager image | `docker compose build --no-cache execution-manager` |
| `gRPC connection failed` | task-service containers not up yet | `docker ps --filter "name=task-service-"` and check their logs |
| Execution-manager reports `0 task(s)` and exits | Started before the deploy-manager filled Redis | Run the deploy-manager first and wait for it to exit with code 0 |
| `gRPC server ... failed to become ready` (deploy-manager) | Port `5005x` already used on the host, or the task-wrapper crashed | `ss -ltnp | grep 5005` and `docker logs task-service-<alias>` |
| `Permission denied` on `/var/run/docker.sock` | User not in `docker` group | `sudo usermod -aG docker $USER` and re-login |
| `SCHED_FIFO` errors | Container missing `SYS_NICE` | Ensure `cap_add: [SYS_NICE]` is present in `docker/orchestration-grpc/compose.yaml` |
| `Container name "/redis" is already in use` | Stale container from a previous run | `start-test.sh` removes it automatically; otherwise: `docker rm -f redis` |
| Port `6379` already in use | A local Redis is already running (Redis uses the host network) | `sudo systemctl stop redis` |
| Tasks miss their deadlines | CPU contention / wrong affinity | Use isolated CPUs (`isolcpus=...` boot param) and pin tasks via `cpu_affinity` |
| The run ignores manifest changes | Manifest baked into the deploy-manager image | Rebuild it: `docker compose build deploy-manager` |

---

<div align="center">


</div>
