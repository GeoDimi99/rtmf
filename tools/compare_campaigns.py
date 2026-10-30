#!/usr/bin/env python3
"""
compare_campaigns.py

Compares two benchmark campaigns run on the same machine, for example the code
before the unification (baseline) and the current one (plan P6), on every
implementation and scenario both campaigns ran.

A campaign is a results root and a RUN_ID. Both result layouts are found:
    <root>/results/<impl>/test_<scenario>_it<N>_<RUN_ID>/   (current layout)
    <root>/<impl>/results/test_<scenario>_it<N>_<RUN_ID>/   (before the unification)

For every pair of runs and every task and metric of perf.csv:
    Welch t-test (two-sided, unpaired), Holm-corrected inside the pair,
    Hedges' g, change of the mean and of the median.
A difference "needs an explanation" when it is significant (Holm p < --alpha)
AND practically large: the mean changes by at least --min-change percent and
by at least --min-abs ms. With 300 iterations per side even tiny differences
are significant, so significance alone is not the criterion.

Before the statistics, every run is checked for missing records and for cores
outside the machine (corrupted log lines).

Writes <out>.csv (every comparison) and <out>.md (summary, data checks and the
differences to explain, with an explanation column to fill in).

Usage:
  python3 tools/compare_campaigns.py --before ~/rtmo-baseline:base --after ~/rtmo:p6 \\
      --out docs/v0.1.0-comparison
"""

import argparse
import csv
import math
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_vs_nonrt_ttest import hedges_g, holm, load_samples, welch_ttest  # noqa: E402

METRICS = ["total_ms", "t_in_tw_ms", "q_em_tw_ms", "q_tw_em_ms"]
IMPLEMENTATIONS = ["choreography-mqueue", "choreography-zeromq", "orchestration-grpc", "orchestration-mqueue"]
NAME = re.compile(r"^test_(?P<scenario>.+)_it(?P<iterations>\d+)_(?P<run>[^_]+)$")


def find_runs(root: Path, run_id: str):
    """{(impl, scenario): result folder} for one campaign."""
    runs = {}
    for impl in IMPLEMENTATIONS:
        for parent in (root / "results" / impl, root / impl / "results"):
            if not parent.is_dir():
                continue
            for d in parent.iterdir():
                m = NAME.match(d.name)
                if m and m.group("run") == run_id and (d / "perf.csv").is_file():
                    runs[(impl, m.group("scenario"))] = d
    return runs


def integrity(run: Path, skip: int):
    """(expected records, found records, records on a core outside 0..63, iterations)."""
    rows = list(csv.DictReader(open(run / "perf.csv", newline="")))
    tasks, iterations = None, None
    manifest = run / "manifest.yaml"
    if manifest.is_file():
        sched = (yaml.safe_load(manifest.read_text()) or {}).get("schedule", {})
        tasks, iterations = len(sched.get("tasks", [])), sched.get("iterations")
    bad_core = sum(1 for r in rows if not 0 <= int(float(r["core_id"])) < 64)
    expected = tasks * iterations if tasks and iterations else None
    return expected, len(rows), bad_core, iterations


def compare_pair(before: Path, after: Path, skip: int, alpha: float, min_change: float, min_abs: float):
    a, b = load_samples(before / "perf.csv", METRICS, skip), load_samples(after / "perf.csv", METRICS, skip)
    rows = []
    for key in sorted(set(a) & set(b)):
        for metric in METRICS:
            x, y = a[key][metric], b[key][metric]
            if len(x) < 2 or len(y) < 2:
                continue
            _, _, p, _ = welch_ttest(x, y)
            mx, my = statistics.fmean(x), statistics.fmean(y)
            rows.append({
                "task_id": key[0], "image": key[1], "metric": metric,
                "n_before": len(x), "n_after": len(y),
                "mean_before_ms": mx, "mean_after_ms": my,
                "median_before_ms": statistics.median(x), "median_after_ms": statistics.median(y),
                "change_ms": my - mx,
                "change_pct": (my - mx) / mx * 100 if mx else math.inf,
                "hedges_g": hedges_g(x, y),
                "welch_p": p,
            })
    for r, adj in zip(rows, holm([r["welch_p"] for r in rows])):
        r["welch_p_holm"] = adj
        r["significant"] = adj < alpha
        r["to_explain"] = (r["significant"] and abs(r["change_pct"]) >= min_change
                           and abs(r["change_ms"]) >= min_abs)
    return rows


def parse_campaign(text: str):
    root, _, run = text.rpartition(":")
    if not root or not run:
        raise argparse.ArgumentTypeError(f"expected <results root>:<RUN_ID>, got {text!r}")
    return Path(root).expanduser().resolve(), run


def fmt(v, digits=3):
    return f"{v:.{digits}f}" if isinstance(v, float) and math.isfinite(v) else str(v)


def main():
    ap = argparse.ArgumentParser(description="Compare two benchmark campaigns (before/after).",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--before", type=parse_campaign, required=True, help="<results root>:<RUN_ID> of the baseline")
    ap.add_argument("--after", type=parse_campaign, required=True, help="<results root>:<RUN_ID> to compare")
    ap.add_argument("--out", type=Path, required=True, help="output path without extension (.csv and .md)")
    ap.add_argument("--skip-iterations", type=int, default=1, help="warm-up iterations to drop (default: %(default)s)")
    ap.add_argument("--alpha", type=float, default=0.05, help="significance level after Holm (default: %(default)s)")
    ap.add_argument("--min-change", type=float, default=5.0, help="smallest relevant change of the mean, %% (default: %(default)s)")
    ap.add_argument("--min-abs", type=float, default=0.05, help="smallest relevant change of the mean, ms (default: %(default)s)")
    args = ap.parse_args()

    (broot, brun), (aroot, arun) = args.before, args.after
    before, after = find_runs(broot, brun), find_runs(aroot, arun)
    pairs = sorted(set(before) & set(after))
    if not pairs:
        ap.error(f"no implementation/scenario ran in both campaigns ({len(before)} runs before, {len(after)} after)")

    all_rows, summary, checks = [], [], []
    for impl, scenario in pairs:
        for side, run in (("before", before[(impl, scenario)]), ("after", after[(impl, scenario)])):
            expected, found, bad, its = integrity(run, args.skip_iterations)
            checks.append((impl, scenario, side, expected, found, bad, its))
        rows = compare_pair(before[(impl, scenario)], after[(impl, scenario)], args.skip_iterations,
                            args.alpha, args.min_change, args.min_abs)
        for r in rows:
            r.update(implementation=impl, scenario=scenario)
        all_rows += rows
        total = [r for r in rows if r["metric"] == "total_ms"]
        biggest = max(rows, key=lambda r: abs(r["change_pct"]) if r["to_explain"] else -1, default=None)
        summary.append({
            "impl": impl, "scenario": scenario, "tests": len(rows),
            "significant": sum(r["significant"] for r in rows),
            "to_explain": sum(r["to_explain"] for r in rows),
            "total_change_pct": statistics.fmean(r["change_pct"] for r in total) if total else float("nan"),
            "biggest": biggest if biggest and biggest["to_explain"] else None,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["implementation", "scenario", "task_id", "image", "metric", "n_before", "n_after",
              "mean_before_ms", "mean_after_ms", "median_before_ms", "median_after_ms", "change_ms", "change_pct",
              "hedges_g", "welch_p", "welch_p_holm", "significant", "to_explain"]
    with open(args.out.with_suffix(".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: (f"{r[k]:.6g}" if isinstance(r[k], float) else r[k]) for k in fields})

    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    md = []
    md.append(f"# Campaign comparison: `{brun}` → `{arun}`\n")
    md.append(f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `tools/compare_campaigns.py`.\n")
    md.append(f"- Before: `{broot}`, RUN_ID `{brun}` ({len(before)} runs)")
    md.append(f"- After: `{aroot}`, RUN_ID `{arun}` ({len(after)} runs)")
    md.append(f"- Compared: {len(pairs)} implementation/scenario pairs, first {args.skip_iterations} iteration(s) dropped")
    md.append(f"- Welch t-test, Holm-corrected per pair, alpha {args.alpha}; a difference needs an explanation when it "
              f"is significant and the mean changes by at least {args.min_change:g} % and {args.min_abs:g} ms")
    if only_before or only_after:
        md.append(f"- Not compared (only in one campaign): {', '.join(f'{i}/{s}' for i, s in only_before + only_after)}")
    md.append("")

    md.append("## Data checks\n")
    problems = [c for c in checks if (c[3] and c[4] != c[3]) or c[5]]
    if problems:
        md.append("| Implementation | Scenario | Campaign | Records expected | Records found | Core outside 0..63 |")
        md.append("|---|---|---|---|---|---|")
        for impl, scenario, side, exp, found, bad, _ in problems:
            md.append(f"| {impl} | {scenario} | {side} | {exp if exp is not None else '?'} | {found} | {bad} |")
    else:
        md.append("Every run has all its records and every record a valid core.")
    md.append("")

    md.append("## Summary\n")
    md.append("`total_ms` is the mean change of the end-to-end time over the tasks of the scenario.\n")
    md.append("| Implementation | Scenario | Tests | Significant | To explain | total_ms change | Largest change to explain |")
    md.append("|---|---|---|---|---|---|---|")
    for s in summary:
        b = s["biggest"]
        big = (f"task {b['task_id']} `{b['metric']}` {b['mean_before_ms']:.3f} → {b['mean_after_ms']:.3f} ms "
               f"({b['change_pct']:+.1f} %)") if b else "–"
        md.append(f"| {s['impl']} | {s['scenario']} | {s['tests']} | {s['significant']} | {s['to_explain']} | "
                  f"{s['total_change_pct']:+.2f} % | {big} |")
    md.append("")

    md.append("## Differences to explain\n")
    flagged = [r for r in all_rows if r["to_explain"]]
    if not flagged:
        md.append("None: no difference is both significant and above the thresholds.\n")
    else:
        md.append("Fill in the last column before tagging the release. Known intended changes: CPU placement from the "
                  "manifest (P5a), Redis and rtmod on core 3, one copy of the task sources (P2: choreography-zeromq lost "
                  "its own debug print), atomic log lines.\n")
        md.append("| Implementation | Scenario | Task | Metric | Before (ms) | After (ms) | Change | Hedges' g | Explanation |")
        md.append("|---|---|---|---|---|---|---|---|---|")
        for r in sorted(flagged, key=lambda r: (r["implementation"], r["scenario"], r["task_id"], r["metric"])):
            md.append(f"| {r['implementation']} | {r['scenario']} | {r['task_id']} | `{r['metric']}` | "
                      f"{r['mean_before_ms']:.3f} | {r['mean_after_ms']:.3f} | {r['change_pct']:+.1f} % | "
                      f"{fmt(r['hedges_g'], 2)} | |")
    md.append("")
    args.out.with_suffix(".md").write_text("\n".join(md))

    print(f"{len(pairs)} pairs, {len(all_rows)} tests, {sum(r['significant'] for r in all_rows)} significant, "
          f"{len(flagged)} to explain; {len(problems)} data problem(s)")
    print(f"wrote {args.out.with_suffix('.csv')} and {args.out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
