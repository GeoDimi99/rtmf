<div align="center">

# ⚡ Orchestration Microservices mqueue

</div>

---

Orchestration pattern of RTMO: a central **execution-manager** reads the schedule from Redis
and dispatches each task to its **task-wrapper** container through POSIX message queues. The
**deploy-manager** starts one task-wrapper container per task image and loads the schedule into
Redis.

## 📁 Repository layout

Paths from the root of the RTMO repository:

```
runtime/common/                                  # logger, task model (same in every implementation)
runtime/orchestration/ipc/mqueue/                # task_ipc.h: message protocol of this implementation
runtime/orchestration/execution-manager/mqueue/  # C: central execution manager
runtime/orchestration/task-wrapper/mqueue/       # C: task-wrapper base image
tooling/builder/                                 # rtmo: builds the base, task (and execution-manager) images
tooling/deploy-manager/                          # rtmod: profile 'orchestration-mqueue' (run_profiles.py), plan encoder encoders/orchestration_mqueue.py
docker/orchestration-mqueue/                     # task-wrapper and execution-manager Dockerfile(s)
benchmarks/scenarios/*.yaml                      # benchmark scenarios, DSL 0.1 (benchmarks branch)
benchmarks/tasks/stress_task_*/                  # task sources, shared by every implementation (benchmarks branch)
tools/run-test.sh                                # one measured run of a manifest
tools/                                           # performance report scripts
results/orchestration-mqueue/                    # one folder per test run (logs, perf.csv, stats.csv, report.pdf)
docs/orchestration-mqueue/                       # this README and notes
```

---

## ⚙️ How it works

1. **`rtmod apply`** (the deploy-manager) reads the manifest and, for every entry of `images`, starts a
   task-wrapper container named after the image alias (`ipc_mode=host`,
   `cap_add=[SYS_NICE, IPC_LOCK]`, `rtprio=99`, `memlock=unlimited`, `cpuset 0-7`,
   env `TASK_NAME` / `TASK_QUEUE_NAME` = alias).
2. It then writes the schedule into Redis:
   - hash `schedule`: `name`, `version`, `description`, `iterations`, `length`
   - hash `scheduletask:<i>` (i = 1..length): `id`, `image`, `start`, `deadline`, `cpu_affinity`,
     `policy`, `priority`, `depends_on`, `inputs`, `outputs`
3. **execution-manager** (started last by `rtmod apply`, `ipc: host`, pinned to CPU 4) waits until the
   `schedule` key exists in Redis, builds the timeline and runs it `iterations` times.
4. Message queues: the execution-manager listens on `/execution_manager_q`; every task-wrapper
   listens on `/<alias>_q` and waits until `/execution_manager_q` exists. At each activation the
   execution-manager sends a request to `/<alias>_q`; the task-wrapper runs `task_main()` in a
   thread with the requested policy/priority/affinity and sends the result back.

Several schedule tasks may use the same image: they are all served by the same container.

---

## 🚀 Running it

Install RTMO once with `install.sh` (see the [repository README](../../README.md)); tests run from
the `benchmarks` branch. One measured run of a scenario on this implementation:

```bash
sudo tools/run-test.sh benchmarks/scenarios/dual_core_sep.yaml my_test \
     --coordination orchestration --technology mqueue --iterations 21
```

Results go to `results/orchestration-mqueue/my_test/` (logs, `manifest.yaml`, `perf.csv`, `stats.csv`,
`report.pdf`). The same run step by step, with the same options on every command:

```bash
O="--coordination orchestration --technology mqueue --iterations 21"
rtmo build       benchmarks/scenarios/dual_core_sep.yaml $O   # images + lock file
sudo rtmod apply benchmarks/scenarios/dual_core_sep.yaml $O   # containers + plan in Redis
sudo rtmod status
sudo rtmod stop
```

The container settings of this implementation are in `tooling/deploy-manager/run_profiles.py`
(profile `orchestration-mqueue`), the Redis plan it reads in `tooling/deploy-manager/encoders/orchestration_mqueue.py`. Manifests
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
gchar *convert_output_to_json(const output_t *output);           /* output_t -> JSON */
void  *task_main(void *arg);   /* arg is an input_t*; returns a g_new0-allocated output_t* */
```

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
deploy-manager     | [INFO] deploy-manager: Processing image 'stress_task_1'
deploy-manager     | [INFO] deploy-manager: Running container 'stress_task_1' from image 'stress_task_1'
deploy-manager     | [INFO] deploy-manager: Container 'stress_task_1' is running (ID: bf34f146ba84)
...
stress_task_1      | [INFO] task-wrapper: stress_task_1: Waiting for Execution Manager queue '/execution_manager_q'...
stress_task_1      | [INFO] task-wrapper: stress_task_1: Connected to Execution Manager queue.
stress_task_1      | [INFO] task-wrapper: === Task Wrapper (stress_task_1) Start Main Loop ===

execution-manager  | [INFO] execution-manager: =========== Execution Manager Init ========
execution-manager  | [INFO] execution-manager: ====== Execution Manager Initialized ======
execution-manager  | [INFO] execution-manager: ==== Execution Manager Start Main Loop ====
execution-manager  | [DEBUG] execution-manager: === SCHEDULE: Configurable CPU/IO Benchmark (v0.0.0) [1300 ms] ===
execution-manager  | [DEBUG] execution-manager:   50 ms: Activate Task 1 (stress_task_1)
execution-manager  | [PERF] execution-manager: iteration=0 task_id=1 ... q_em_tw_ms=0.361 t_in_tw_ms=86.954 q_tw_em_ms=0.083 total_ms=87.397 core_id=4
...
execution-manager  | [INFO] execution-manager: ==== Execution Manager Exit Main Loop ====
execution-manager  | [INFO] execution-manager: Cleanup completed.
```

The `[PERF]` lines are what `tools/perf_report.py` turns into `perf.csv`, `stats.csv` and `report.pdf`.

---

## ❗ Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Stale task results across runs | POSIX queues persist on the host | `sudo rm -f /dev/mqueue/*` before relaunching |
| Tasks miss their deadlines | CPU contention / wrong affinity | Use isolated CPUs (`isolcpus=...` boot param) and pin tasks via `cpu_affinity` |

More, for installing and running RTMO: the troubleshooting table of the RTMO Field Guide and `tooling/README.md`.

---

<div align="center">


</div>
