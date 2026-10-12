"""Summarise scaling runs written by run_scale.sh into data/scale.csv.

    python analyze_scale.py <scale-dir> [<scale-dir> ...]
"""
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("analyze_e1", HERE / "analyze_e1.py")
e1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e1)


def summarise(run_dir):
    run_dir = Path(run_dir)
    events = e1.parse_events(run_dir / "events.log")
    sim_text = (run_dir / "log_sim.txt").read_text(encoding="utf-8", errors="replace")
    rooms = re.search(r"Simulating \d+ rooms: (.*)", sim_text).group(1).split(", ")
    e1.ROOMS = rooms
    steps = e1.parse_sim(run_dir / "log_sim.txt")
    dec_lines = list(e1.read_lines(run_dir / "log_dec.txt"))
    # Skip the first step (subscriptions not yet in place) and the last (its
    # receipts may postdate the log capture).
    window_end = steps[-1]["real"]
    measured = steps[1:-1]
    latency, *_ = e1.latency(measured, dec_lines, window_end)
    stuck_alarms = sum(1 for _, text in dec_lines if "reading is stuck" in text)
    stepping = e1.step_interval(steps, window_end)
    memory = e1.memory(run_dir / "stats.txt")
    free = (run_dir / "free.txt").read_text().split("\n")[1].split()
    containers = [line.split() for line in (run_dir / "containers.txt").read_text().splitlines()]
    restarts = sum(int(fields[1].split("=")[1]) for fields in containers)
    running = sum(fields[2] == "status=running" for fields in containers)
    python_kinds = ("occ", "sensor", "sensor-co2", "hvac", "vent", "dec", "sim", "metrics-exporter")
    python = [m for kind, m in memory.items() if kind in python_kinds]
    return {
        "rooms": len(rooms),
        "containers_running": running,
        "project_mem_MiB": round(sum(m["total_MiB"] for m in memory.values())),
        "python_container_mean_MiB": round(
            sum(m["total_MiB"] for m in python) / sum(m["count"] for m in python), 1
        ),
        "vm_used_MiB": int(free[2]),
        "vm_total_MiB": int(free[1]),
        "restarts": restarts,
        "up_s": round((events["up done"] - events["up start"]).total_seconds()),
        "first_step_after_up_s": round((events["first sim step"] - events["up done"]).total_seconds()),
        "steps": len(steps),
        "step_work_p50_ms": round(stepping["step_work_p50_ms"], 1),
        "step_work_max_ms": round(stepping["step_work_max_ms"], 1),
        "interval_p50_s": round(stepping["interval_p50_s"], 2),
        "latency_total_p50_ms": round(latency["total"]["p50_ms"], 1),
        "latency_total_p95_ms": round(latency["total"]["p95_ms"], 1),
        "missing_decisions": latency["missing_decisions"],
        "expected_decisions": latency["expected_decisions"],
        "stuck_alarms": stuck_alarms,
        "memory_by_kind": memory,
    }


def main():
    rows = sorted((summarise(path) for path in sys.argv[1:]), key=lambda row: row["rooms"])
    fields = [key for key in rows[0] if key != "memory_by_kind"]
    with (e1.DATA_DIR / "scale.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    (e1.DATA_DIR / "scale_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
