<div align="center">

# 🎼 Choreography Microservices ZeroMQ
</div>

---

Choreography pattern of RTMO: there is no central execution manager. The **deploy-manager**
starts one **task-wrapper** container per task image and loads a distributed execution plan into
Redis; every task-wrapper reads its own part of the plan, joins a start barrier over ZeroMQ
(Unix-domain sockets in a shared volume) and then runs its own timeline.

## 📁 Repository layout

Paths from the root of the RTMO repository:

```
runtime/common/                            # logger, task model (same in every implementation)
runtime/choreography/ipc/zeromq/           # task_ipc.h: message protocol of this implementation
runtime/choreography/task-wrapper/zeromq/  # C: task-wrapper base image (local execution manager + task harness)
tooling/builder/                           # rtmo: builds the base, task (and execution-manager) images
tooling/deploy-manager/                    # rtmod: profile 'choreography-zeromq' (run_profiles.py), plan encoder encoders/choreography.py
docker/choreography-zeromq/                # task-wrapper Dockerfile(s)
benchmarks/scenarios/*.yaml                # benchmark scenarios, DSL 0.1 (benchmarks branch)
benchmarks/tasks/stress_task_*/            # task sources, shared by every implementation (benchmarks branch)
tools/run-test.sh                          # one measured run of a manifest
tools/                                     # performance report scripts
results/choreography-zeromq/               # one folder per test run (logs, perf.csv, stats.csv, report.pdf)
docs/choreography-zeromq/                  # this README and notes
```

---

## ⚙️ How it works

1. **`rtmod apply`** (the deploy-manager) reads the manifest and, for every entry of `images`, starts a
   task-wrapper container named after the image alias. The containers join the device network `rtmo`
   (so they can reach `redis`), mount the named volume `zmq_ipc` on `/ipc` and get
   `cap_add=[SYS_NICE, IPC_LOCK]`, `rtprio=99`, `memlock=unlimited`, `cpuset` = the manifest's `control_cpu` + `task_cpus`, env `RTMO_CONTROL_CPU` / `RTMO_TASK_CPUS`,
   env `TASK_NAME` / `TASK_QUEUE_NAME` = alias.
2. It then writes the distributed plan into a single Redis hash, `schedule_data`:
   - `schedule:name`, `schedule:version`, `schedule:description`, `schedule:iterations`
   - `schedule:images`: JSON list of the images, `schedule:length`: number of images
   - `schedule:duration`: latest deadline (ms), the length of one iteration
   - `schedule:leader`: the image of the task with the earliest `start`
   - `schedule:<image>:length` and `schedule:<image>:<idx>`: the tasks of each image, as JSON
3. Every task-wrapper (entrypoint `./build/execution-manager`) polls Redis until `schedule_data`
   exists and loads only the tasks of its own image.
4. **Start barrier over ZeroMQ**: the leader binds a `PULL` socket on `ipc:///ipc/sync_ready.sock`
   and an `XPUB` socket on `ipc:///ipc/sync_pub.sock`; every worker connects a `PUSH` and a `SUB`
   socket, then sends `READY`. When all the workers are ready the leader broadcasts the common t₀.
   Then every container runs its own timeline `iterations` times and exits when the final deadline
   is reached.

---

## 🚀 Running it

Install RTMO once with `install.sh` (see the [repository README](../../README.md)); tests run from
the `benchmarks` branch. One measured run of a scenario on this implementation:

```bash
sudo tools/run-test.sh benchmarks/scenarios/dual_core_sep.yaml my_test \
     --coordination choreography --technology zeromq --iterations 21
```

Results go to `results/choreography-zeromq/my_test/` (logs, `manifest.yaml`, `perf.csv`, `stats.csv`,
`report.pdf`). The same run step by step, with the same options on every command:

```bash
O="--coordination choreography --technology zeromq --iterations 21"
rtmo build       benchmarks/scenarios/dual_core_sep.yaml $O   # images + lock file
sudo rtmod apply benchmarks/scenarios/dual_core_sep.yaml $O   # containers + plan in Redis
sudo rtmod status
sudo rtmod stop
```

The container settings of this implementation are in `tooling/deploy-manager/run_profiles.py`
(profile `choreography-zeromq`), the Redis plan it reads in `tooling/deploy-manager/encoders/choreography.py`. Manifests
use the RTMO DSL 0.1 (`tooling/README.md`); the whole campaign is `benchmarks/run-campaign.sh`.

---

## ➕ Adding a new task

1. Create `benchmarks/tasks/<my_task>/app_task.h` and `app_task.c` (start from `benchmarks/tasks/stress_task_1/`).
2. In a manifest, add the image `{name: my_task, src: ../tasks/my_task}` under `images`.
3. Add one or more entries under `schedule.tasks` with `image: my_task`.
4. Check it with `rtmo validate <manifest>`, then run it with `tools/run-test.sh` as above.

---

## 🖥️ Sample output

Excerpt of a run with the default six-task manifest (100 iterations); `stress_task_1` is the leader:

```text
deploy-manager     | [INFO] deploy-manager: Processing image 'stress_task_1'
deploy-manager     | [INFO] deploy-manager: Running container 'stress_task_1' from image 'stress_task_1'
deploy-manager     | [INFO] deploy-manager: Container 'stress_task_1' is running on network 'choreography-zeromq_default' (ID: 4755fc27ebc7)
...

stress_task_1      | [INFO] task-wrapper: Initialized (Click Ctrl+C for a clean exit)
stress_task_1      | [INFO] task-wrapper: Waiting for schedule_data in Redis...
stress_task_1      | [INFO] task-wrapper: Leader: PULL bound on ipc:///ipc/sync_ready.sock
stress_task_1      | [INFO] task-wrapper: Leader: XPUB bound on ipc:///ipc/sync_pub.sock
stress_task_1      | [INFO] execution-manager: >>> SCHEDULE INFO
stress_task_1      | [INFO] execution-manager:     Duration:  1300 ms
stress_task_1      | [INFO] execution-manager:     @ 50     ms | ID: 1   | stress_task_1    | Core: 5  | Prio: 50  | FIFO
stress_task_1      | [PERF] task-wrapper: iteration=0 task_id=1 ... q_em_tw_ms=0.197 t_in_tw_ms=87.295 q_tw_em_ms=0.006 total_ms=87.498 core_id=5
...
stress_task_1      | [INFO] task-wrapper: handle_expiration: Final deadline reached. Quitting...
stress_task_1      | [INFO] task-wrapper: Cleanup completed

stress_task_2      | [INFO] task-wrapper: Worker: SUB connected to ipc:///ipc/sync_pub.sock
stress_task_2      | [INFO] task-wrapper: Worker: PUSH connected to ipc:///ipc/sync_ready.sock
```

The `[PERF]` lines of all task containers are what `tools/perf_report.py` turns into `perf.csv`,
`stats.csv` and `report.pdf`.

---

## ❗ Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Source path '<path>' for alias '<alias>' does not exist.` (image-builder) | A `src:` folder declared in the manifest does not exist on disk | Create the missing `benchmarks/tasks/<alias>/` folder, or remove the alias from `manifest.yaml` |
| Task containers hang at the start barrier | Some task containers crashed before sending `READY` | `docker ps -a --filter "name=stress_task_"` and check the logs of the missing ones |
| `zmq_bind(PULL) failed` / `zmq_bind(XPUB) failed` | Stale Unix socket file in the shared volume | The leader unlinks them at start; if not, `docker volume rm zmq_ipc && docker volume create zmq_ipc` |
| `SCHED_FIFO` / `mlock` errors | Container missing capabilities or `rtprio` ulimit | `rtmod apply` sets them (profile `choreography-zeromq` in `tooling/deploy-manager/run_profiles.py`); check with `docker inspect <alias>` |
| Tasks miss their deadlines | CPU contention / wrong affinity | Use isolated CPUs (`isolcpus=...` boot param) and pin tasks via `cpu_affinity` |

More, for installing and running RTMO: the troubleshooting table of the RTMO Field Guide and `tooling/README.md`.

---

<div align="center">

</div>
