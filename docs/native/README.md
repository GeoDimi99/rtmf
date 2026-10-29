<div align="center">

# ⚡ RealTime Native Execution Manager

</div>

---

Baseline of RTMO without containers: a single host process (the **Execution Manager**) runs the
whole schedule, launching every task as a real-time thread. There is no manifest, no Redis and
no Docker: the schedule is defined in C in `runtime/native/execution-manager/src/main.c`.

## 📁 Repository layout

Paths from the root of the RTMO repository:

```
runtime/common/shared/             # logger, task model (same in every implementation)
runtime/common/native/             # task.h of this implementation
runtime/native/execution-manager/  # C: host process, schedule in src/main.c
tests/start-test/native.sh         # end-to-end build, run & benchmark
tools/                             # performance report scripts
results/native/                    # one folder per test run (logs, perf.csv, stats.csv, report.pdf)
docs/native/                       # this README and notes
```

## 📋 Prerequisites

- **Linux host with `PREEMPT_RT` kernel** (`SCHED_FIFO`, `mlockall`, `SYS_NICE` and POSIX timers are required for deterministic scheduling).
- **CMake ≥ 3.20**, a C compiler, `pkg-config` and GLib (`libglib2.0-dev`, which also provides `gio-2.0`).
- **Python 3** for the performance report (`start-test.sh` installs `matplotlib`, `numpy` and
  `PyYAML` into `tools/.venv` when they are missing).
- Root privileges (or `CAP_SYS_NICE` + `CAP_IPC_LOCK`) for `SCHED_FIFO` and `mlockall`.

---

## 🚀 Automated start

```bash
git clone https://github.com/GeoDimi99/RTMO.git
cd RTMO/native
sudo tests/start-test/native.sh [test-name]
```

`start-test.sh` configures and builds the Execution Manager with CMake, runs it, saves its
output in `results/native/<test-name>/execution-manager.log` (a random `results/native/test_<id>/` when no name
is given) and generates the performance report there. Ctrl+C stops the run early; the report is
built from the data collected so far.

| Variable | Meaning |
|---|---|
| `CMAKE=<path>` | cmake binary to use (default: auto-detected). |
| `FORCE=1` | Overwrite `results/native/<test-name>/` if it already exists. |

---

## 🛠️ Manual workflow

Follow these steps to build and start the system step by step:

```bash
# 1. Configure the build
cmake -S runtime/native/execution-manager -B runtime/native/execution-manager/build

# 2. Compile the Execution Manager
cmake --build runtime/native/execution-manager/build

# 3. Run it (sudo required for SCHED_FIFO + mlockall)
sudo ./runtime/native/execution-manager/build/execution-manager

# 4. Clean the build tree
rm -rf runtime/native/execution-manager/build
```

> Add `--clean-first` to step 2, or simply remove the `build/` directory, to
> force a clean rebuild.

---

## ⚙️ Runtime behaviour

- The Execution Manager pins itself to CPU 4 (`DEFAULT_EM_CPU_AFFINITY`), locks its memory and
  runs with `SCHED_FIFO` priority 95.
- The schedule is replayed 100 times (`num_iter` in `main.c`); every task emits a `[PERF]` line
  that `tools/perf_report.py` turns into `perf.csv`, `stats.csv` and `report.pdf`.
- The active schedule is the six-task benchmark used by the containerised implementations
  (`stress_task_1..6`, `SCHED_FIFO`, CPU 5); other test scenarios are kept commented out in `main.c`.

### Adding a task

Edit the schedule in `runtime/native/execution-manager/src/main.c`:

```c
schedule_add_task(
    sched,
    /* id            */ 1,
    /* name          */ "stress_task_1",
    /* exec function */ task_main,
    /* policy        */ SCHED_FIFO,
    /* priority      */ 50,
    /* cpu_affinity  */ 5,
    /* repetition    */ 1,
    /* depends_on    */ NULL,
    /* start_time_ms */ 50,
    /* end_time_ms   */ 650,
    /* input         */ func_input
);
```

`func_input` is a `g_new0`-allocated `input_t` (see `include/app_task.h`).

---


<div align="center">

</div>
