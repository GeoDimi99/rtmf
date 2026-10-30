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
runtime/common/                                # logger, task model (same in every implementation)
runtime/orchestration/ipc/grpc/                # task_ipc.h: message protocol of this implementation
runtime/orchestration/execution-manager/grpc/  # C/C++: central execution manager (gRPC client)
runtime/orchestration/task-wrapper/grpc/       # C/C++: task-wrapper base image (gRPC server)
runtime/proto/task_service.proto               # gRPC service definition
tooling/builder/                               # rtmo: builds the base, task (and execution-manager) images
tooling/deploy-manager/                        # rtmod: profile 'orchestration-grpc' (run_profiles.py), plan encoder encoders/orchestration_grpc.py
docker/orchestration-grpc/                     # task-wrapper and execution-manager Dockerfile(s)
benchmarks/scenarios/*.yaml                    # benchmark scenarios, DSL 0.1 (benchmarks branch)
benchmarks/tasks/stress_task_*/                # task sources, shared by every implementation (benchmarks branch)
tools/run-test.sh                              # one measured run of a manifest
tools/                                         # performance report scripts
results/orchestration-grpc/                    # one folder per test run (logs, perf.csv, stats.csv, report.pdf)
docs/orchestration-grpc/                       # this README and notes
```

---

## ⚙️ How it works

1. **`rtmod apply`** (the deploy-manager, host network) reads the manifest and assigns one gRPC port
   to each entry of `images`, in order: `50051`, `50052`, ... For every image it starts a container named
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


## 🚀 Running it

Install RTMO once with `install.sh` (see the [repository README](../../README.md)); tests run from
the `benchmarks` branch. One measured run of a scenario on this implementation:

```bash
sudo tools/run-test.sh benchmarks/scenarios/dual_core_sep.yaml my_test \
     --coordination orchestration --technology grpc --iterations 21
```

Results go to `results/orchestration-grpc/my_test/` (logs, `manifest.yaml`, `perf.csv`, `stats.csv`,
`report.pdf`). The same run step by step, with the same options on every command:

```bash
O="--coordination orchestration --technology grpc --iterations 21"
rtmo build       benchmarks/scenarios/dual_core_sep.yaml $O   # images + lock file
sudo rtmod apply benchmarks/scenarios/dual_core_sep.yaml $O   # containers + plan in Redis
sudo rtmod status
sudo rtmod stop
```

The container settings of this implementation are in `tooling/deploy-manager/run_profiles.py`
(profile `orchestration-grpc`), the Redis plan it reads in `tooling/deploy-manager/encoders/orchestration_grpc.py`. Manifests
use the RTMO DSL 0.1 (`tooling/README.md`); the whole campaign is `benchmarks/run-campaign.sh`.

---

## 🧩 Task API

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

---

## ➕ Adding a new task

1. Create `benchmarks/tasks/<my_task>/app_task.h` and `app_task.c` (start from `benchmarks/tasks/stress_task_1/`).
2. In a manifest, add the image `{name: my_task, src: ../tasks/my_task}` under `images`.
3. Add one or more entries under `schedule.tasks` with `image: my_task`.
4. Check it with `rtmo validate <manifest>`, then run it with `tools/run-test.sh` as above.

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

## ❗ Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `gRPC connection failed` | task-service containers not up yet | `docker ps --filter "name=task-service-"` and check their logs |
| Execution-manager reports `0 task(s)` and exits | Started before the deploy-manager filled Redis | Run the deploy-manager first and wait for it to exit with code 0 |
| Tasks miss their deadlines | CPU contention / wrong affinity | Use isolated CPUs (`isolcpus=...` boot param) and pin tasks via `cpu_affinity` |

More, for installing and running RTMO: the troubleshooting table of the RTMO Field Guide and `tooling/README.md`.

---

<div align="center">


</div>
