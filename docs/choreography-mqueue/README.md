<div align="center">

# 🎼 Choreography Microservices MQueue
</div>


---

Choreography pattern of RTMO: there is no central execution manager. The **deploy-manager**
starts one **task-wrapper** container per task image and loads a distributed execution plan into
Redis; every task-wrapper reads its own part of the plan, joins a start barrier through POSIX
message queues and then runs its own timeline.

## 📁 Repository layout

Paths from the root of the RTMO repository:

```
runtime/common/                            # logger, task model (same in every implementation)
runtime/choreography/ipc/mqueue/           # task_ipc.h: message protocol of this implementation
runtime/choreography/task-wrapper/mqueue/  # C: task-wrapper base image (local execution manager + task harness)
tooling/builder/                           # rtmo: builds the base, task (and execution-manager) images
tooling/deploy-manager/                    # rtmod: profile 'choreography-mqueue' (run_profiles.py), plan encoder encoders/choreography.py
docker/choreography-mqueue/                # task-wrapper Dockerfile(s)
benchmarks/scenarios/*.yaml                # benchmark scenarios, DSL 0.1 (benchmarks branch)
benchmarks/tasks/stress_task_*/            # task sources, shared by every implementation (benchmarks branch)
tools/run-test.sh                          # one measured run of a manifest
tools/                                     # performance report scripts
results/choreography-mqueue/               # one folder per test run (logs, perf.csv, stats.csv, report.pdf)
docs/choreography-mqueue/                  # this README and notes
```

---

## ⚙️ How it works

1. **`rtmod apply`** (the deploy-manager) reads the manifest and, for every entry of `images`, starts a
   task-wrapper container named after the image alias. The containers join the device network `rtmo`
   (so they can reach `redis`) and get `ipc_mode=host`, `cap_add=[SYS_NICE, IPC_LOCK]`,
   `rtprio=99`, `memlock=unlimited`, `cpuset` = the manifest's `control_cpu` + `task_cpus`, env `RTMO_CONTROL_CPU` / `RTMO_TASK_CPUS`, env `TASK_NAME` / `TASK_QUEUE_NAME` = alias.
2. It then writes the distributed plan into a single Redis hash, `schedule_data`:
   - `schedule:name`, `schedule:version`, `schedule:description`, `schedule:iterations`
   - `schedule:images`: JSON list of the images, `schedule:length`: number of images
   - `schedule:duration`: latest deadline (ms), the length of one iteration
   - `schedule:leader`: the image of the task with the earliest `start`
   - `schedule:<image>:length` and `schedule:<image>:<idx>`: the tasks of each image, as JSON
3. Every task-wrapper (entrypoint `./build/execution-manager`) polls Redis until `schedule_data`
   exists, loads only the tasks of its own image and opens its queue `/<alias>_q`.
4. **Start barrier**: the workers send `READY` to the leader's queue; when all of them are ready
   the leader broadcasts `SYNC` with a common t₀. Then every container runs its own timeline
   `iterations` times and exits when the final deadline is reached.

---

## 🚀 Running it

Install RTMO once with `install.sh` (see the [repository README](../../README.md)); tests run from
the `benchmarks` branch. One measured run of a scenario on this implementation:

```bash
sudo tools/run-test.sh benchmarks/scenarios/dual_core_sep.yaml my_test \
     --coordination choreography --technology mqueue --iterations 21
```

Results go to `results/choreography-mqueue/my_test/` (logs, `manifest.yaml`, `perf.csv`, `stats.csv`,
`report.pdf`). The same run step by step, with the same options on every command:

```bash
O="--coordination choreography --technology mqueue --iterations 21"
rtmo build       benchmarks/scenarios/dual_core_sep.yaml $O   # images + lock file
sudo rtmod apply benchmarks/scenarios/dual_core_sep.yaml $O   # containers + plan in Redis
sudo rtmod status
sudo rtmod stop
```

The container settings of this implementation are in `tooling/deploy-manager/run_profiles.py`
(profile `choreography-mqueue`), the Redis plan it reads in `tooling/deploy-manager/encoders/choreography.py`. Manifests
use the RTMO DSL 0.1 (`tooling/README.md`); the whole campaign is `benchmarks/run-campaign.sh`.

---

## ➕ Adding a new task

1. Create `benchmarks/tasks/<my_task>/app_task.h` and `app_task.c` (start from `benchmarks/tasks/stress_task_1/`).
2. In a manifest, add the image `{name: my_task, src: ../tasks/my_task}` under `images`.
3. Add one or more entries under `schedule.tasks` with `image: my_task`.
4. Check it with `rtmo validate <manifest>`, then run it with `tools/run-test.sh` as above.

---

## 🖥️ Sample output

Excerpt of a run with the default six-task manifest (100 iterations):

```text
deploy-manager     | [INFO] deploy-manager: Processing image 'stress_task_1'
deploy-manager     | [INFO] deploy-manager: Running container 'stress_task_1' from image 'stress_task_1'
deploy-manager     | [INFO] deploy-manager: Container 'stress_task_1' is running on network 'choreography-mqueue_default' (ID: a892e21e2500)
...

stress_task_1      | [INFO] task-wrapper: Initialized (Click Ctrl+C for a clean exit)
stress_task_1      | [INFO] task-wrapper: Waiting for schedule_data in Redis...
stress_task_1      | [DEBUG] execution-manager: Name: Configurable CPU/IO Benchmark
stress_task_1      | [DEBUG] execution-manager: Duration: 1300 ms
stress_task_1      | [DEBUG] execution-manager: @ 50     ms | ID: 1   | stress_task_1    | Core: 5  | Prio: 50  | FIFO
stress_task_1      | [PERF] task-wrapper: iteration=0 task_id=1 ... q_em_tw_ms=0.185 t_in_tw_ms=86.778 q_tw_em_ms=0.019 total_ms=86.983 core_id=5
...
stress_task_1      | [INFO] task-wrapper: handle_expiration: final deadline reached. Quitting...
stress_task_1      | [INFO] task-wrapper: Cleanup completed
```

The `[PERF]` lines of all task containers are what `tools/perf_report.py` turns into `perf.csv`,
`stats.csv` and `report.pdf`.

---

## ❗ Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Tasks exit immediately with `Exited (0)` and `COMMAND="/bin/bash"` | Per-task images were built without an entrypoint (image-builder step failed or skipped) | Re-run `rtmo build <manifest>` and check it ends with `built … task image(s)`. Verify with `docker inspect <alias> --format '{{.Config.Entrypoint}}'`. |
| `mq_open: Permission denied` / tasks hang on first message | `/dev/mqueue` not writable from the container | Make sure POSIX message queues are exposed by the kernel; `deploy-manager` already starts the wrappers with `ipc_mode=host`. |
| Tasks miss their deadlines | CPU contention / wrong affinity | Use isolated CPUs (`isolcpus=...` boot param) and pin tasks via `cpu_affinity`. |
| `sched_setscheduler failed: Operation not permitted` | Container missing `SYS_NICE` capability or `rtprio` ulimit | The `deploy-manager` already passes `cap_add=[SYS_NICE, IPC_LOCK]` and `rtprio=99`; don't run wrappers manually without those flags. |
| `cmake: not found` while the image-builder is building a task | Base image was rebuilt without the build toolchain | Force a clean rebuild: `docker rmi rtmo/task-wrapper:choreography-mqueue && docker build --no-cache -t rtmo/task-wrapper:choreography-mqueue -f runtime/choreography/task-wrapper/mqueue/Dockerfile .` |

More, for installing and running RTMO: the troubleshooting table of the RTMO Field Guide and `tooling/README.md`.

---

<div align="center">

</div>
