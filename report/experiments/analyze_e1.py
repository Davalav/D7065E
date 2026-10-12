"""Turn the logs of experiment E1 (nominal run + fault injection E2-E5) into
the numbers and CSV files used in Section 11 of the report.

    python analyze_e1.py <e1-output-dir>

Reads log_sim.txt, log_dec.txt, inspect.txt, stats_*.txt and events.log written
by run_e1.sh. All latencies are computed from Docker log timestamps, which come
from one clock (the Docker VM), so host/VM clock skew does not enter them.
"""
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


REPORT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = REPORT_DIR / "data"
ROOMS = ["A107", "A108", "A109", "A110", "A111"]

LINE = re.compile(r"^(\S+Z) (.*)$")
HEADER = re.compile(r"^(\d{4}-\d\d-\d\dT[\d:]+)\+00:00 \| ([-\d.]+) °C outside")
ROOM_LINE = re.compile(
    r"^\s+(\S+) \| (\d+) occupants \| ([-\d.]+) W HVAC \| ([-\d.]+) W vent \| "
    r"([-\d.]+) °C \| ([-\d.]+) ppm CO2"
)
RECEIVED = re.compile(r"Mottaget meddelande på '0/([^/]+)/(temp|co2)/dec'")
PID_LINE = re.compile(r"^(\S+) (temp|co2) PID: ([-\d.]+) -> ([-\d.]+) W")
CONFIRMED = re.compile(r"([^\s:]+) (temp|co2) actuator command (\d+) confirmed")
RETRY = re.compile(r"([^\s:]+) (temp|co2) actuator did not confirm command (\d+)")
FAILSAFE = re.compile(r"([^\s:]+) (temp|co2) sensor (data is stale|reading is stuck); entering fail-safe")
RECOVERED = re.compile(r"([^\s:]+) (temp|co2) sensor recovered")
SETPOINT = re.compile(r"Setpoint changed to ([\d.]+) for (\S+) temp")


def parse_ts(text):
    # Docker gives nanoseconds; datetime takes microseconds.
    text = text.rstrip("Z")
    if "." in text:
        head, frac = text.split(".")
        text = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(text)


def read_lines(path):
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LINE.match(raw)
        if match:
            yield parse_ts(match.group(1)), match.group(2)


def setpoint_at(sim_time):
    return 17.0 if sim_time.hour >= 18 or sim_time.hour < 6 else 21.0


def parse_sim(path):
    steps = []
    current = None
    for ts, text in read_lines(path):
        header = HEADER.match(text)
        if header:
            current = {
                "real": ts,
                "sim": datetime.fromisoformat(header.group(1)),
                "outside": float(header.group(2)),
                "rooms": {},
                "last_line": ts,
            }
            steps.append(current)
            continue
        room = ROOM_LINE.match(text)
        if room and current is not None:
            current["rooms"][room.group(1)] = {
                "occ": int(room.group(2)),
                "hvac": float(room.group(3)),
                "vent": float(room.group(4)),
                "temp": float(room.group(5)),
                "co2": float(room.group(6)),
            }
            current["last_line"] = ts
    return [step for step in steps if len(step["rooms"]) == len(ROOMS)]


def parse_events(path):
    events = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stamp, _, label = line.partition(" ")
        events[label] = parse_ts(stamp)
    return events


def parse_inspect(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split()[0].strip("/")
        fields = dict(item.split("=", 1) for item in line.split()[1:])
        result[name] = fields
    return result


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = (len(ordered) - 1) * q
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def comfort_and_energy(steps):
    """FR-1, FR-2, FR-4 metrics over the nominal window."""
    per_room = {}
    for room in ROOMS:
        reached_at = None
        in_band = total_day = 0
        energy_day = energy_night = 0.0
        recovery = []
        morning_start = None
        max_occ = 0
        occupied_steps = 0
        occupied_in_band = 0
        for step in steps:
            state = step["rooms"][room]
            sp = setpoint_at(step["sim"])
            if state["occ"] > 0:
                occupied_in_band += abs(state["temp"] - 21.0) <= 1.0
            joules = state["hvac"] * 300
            if sp == 21.0:
                energy_day += joules
            else:
                energy_night += joules
            max_occ = max(max_occ, state["occ"])
            occupied_steps += state["occ"] > 0
            if reached_at is None and state["temp"] >= 21.0 - 0.5 and sp == 21.0:
                reached_at = step["sim"]
            if reached_at is not None and sp == 21.0:
                total_day += 1
                in_band += abs(state["temp"] - sp) <= 1.0
            # Morning recovery after a setback: 06:00 until within 1 °C of 21.
            if step["sim"].hour == 6 and step["sim"].minute < 5:
                morning_start = step["sim"]
            if morning_start is not None and abs(state["temp"] - 21.0) <= 1.0:
                recovery.append((step["sim"] - morning_start).total_seconds() / 3600)
                morning_start = None
        per_room[room] = {
            "first_within_0.5C": reached_at.isoformat() if reached_at else None,
            "hours_to_reach": (
                (reached_at - steps[0]["sim"]).total_seconds() / 3600 if reached_at else None
            ),
            "day_steps_in_band_pct": 100 * in_band / total_day if total_day else None,
            "day_steps_after_reach": total_day,
            "energy_day_kWh": energy_day / 3.6e6,
            "energy_night_kWh": energy_night / 3.6e6,
            "morning_recovery_h": recovery,
            "max_occupants": max_occ,
            "occupied_steps": occupied_steps,
            "occupied_in_band_pct": 100 * occupied_in_band / occupied_steps if occupied_steps else None,
        }
    return per_room


def co2_metrics(steps):
    per_room = {}
    for room in ROOMS:
        occupied = above_1000 = 0
        high = responded = 0
        peak = 0.0
        for previous, step in zip(steps, steps[1:]):
            before = previous["rooms"][room]
            state = step["rooms"][room]
            peak = max(peak, state["co2"])
            if state["occ"] > 0:
                occupied += 1
                above_1000 += state["co2"] > 1000
            # A reading above 900 ppm in step k is answered by the vent power the
            # simulator reads at the start of step k+1 (one-step actuation lag).
            if before["co2"] > 900:
                high += 1
                responded += state["vent"] > 0
        per_room[room] = {
            "peak_ppm": peak,
            "occupied_steps": occupied,
            "occupied_above_1000_pct": 100 * above_1000 / occupied if occupied else None,
            "steps_above_900": high,
            "vent_on_next_step_pct": 100 * responded / high if high else None,
        }
    return per_room


def latency(steps, dec_lines, window_end):
    """NFR-1: sim publish -> decision maker receipt -> actuator confirmed."""
    received = defaultdict(list)
    confirmed = defaultdict(list)
    for ts, text in dec_lines:
        if ts > window_end:
            break
        match = RECEIVED.search(text)
        if match:
            received[(match.group(1), match.group(2))].append(ts)
            continue
        match = CONFIRMED.search(text)
        if match:
            confirmed[(match.group(1), match.group(2))].append(ts)
    sense, act, total, missing = [], [], [], 0
    for step in steps:
        if step["real"] > window_end:
            break
        published = step["last_line"]
        for room in ROOMS:
            for signal in ("temp", "co2"):
                key = (room, signal)
                recv = next((t for t in received[key] if t >= published), None)
                if recv is None or (recv - published).total_seconds() > 4:
                    missing += 1
                    continue
                ack = next((t for t in confirmed[key] if t >= recv), None)
                if ack is None or (ack - recv).total_seconds() > 4:
                    missing += 1
                    continue
                sense.append((recv - published).total_seconds() * 1000)
                act.append((ack - recv).total_seconds() * 1000)
                total.append((ack - published).total_seconds() * 1000)
    summary = {
        name: {
            "n": len(values),
            "p50_ms": percentile(values, 0.5),
            "p95_ms": percentile(values, 0.95),
            "max_ms": max(values) if values else None,
        }
        for name, values in (("sense", sense), ("act", act), ("total", total))
    }
    summary["missing_decisions"] = missing
    summary["expected_decisions"] = sum(
        1 for step in steps if step["real"] <= window_end
    ) * len(ROOMS) * 2
    return summary, sense, act, total


def step_interval(steps, window_end):
    gaps = [
        (b["real"] - a["real"]).total_seconds()
        for a, b in zip(steps, steps[1:])
        if b["real"] <= window_end
    ]
    work = [
        (step["last_line"] - step["real"]).total_seconds() * 1000
        for step in steps
        if step["real"] <= window_end
    ]
    return {
        "interval_p50_s": percentile(gaps, 0.5),
        "interval_max_s": max(gaps),
        "step_work_p50_ms": percentile(work, 0.5),
        "step_work_max_ms": max(work),
    }


def faults(dec_lines, sim_steps, inspect, events):
    result = {}
    lines = list(dec_lines)

    def first(pattern, after, room=None, signal=None, before=None):
        for ts, text in lines:
            if ts < after or (before and ts > before):
                continue
            match = pattern.search(text)
            if match and (room is None or match.group(1) == room) and (
                signal is None or match.group(2) == signal
            ):
                return ts, text
        return None, None

    def last(pattern, before, room, signal):
        found = None
        for ts, text in lines:
            if ts > before:
                break
            match = pattern.search(text)
            if match and match.group(1) == room and match.group(2) == signal:
                found = ts
        return found

    def pid_count(after, before, exclude=None):
        count = 0
        for ts, text in lines:
            if after <= ts <= before:
                match = PID_LINE.match(text)
                if match and match.group(1) != exclude:
                    count += 1
        return count

    # E2: A110 temperature sensor stopped for 60 s.
    sensor = inspect["d7065e-sensor-r009-a110-1"]
    stopped = events["E2 stop sensor-r009-a110"]
    started = parse_ts(sensor["started"])
    fs_ts, _ = first(FAILSAFE, stopped - timedelta(seconds=5), "A110", "temp")
    last_reading = last(RECEIVED_ROOM, fs_ts, "A110", "temp") if fs_ts else None
    rec_ts, _ = first(RECOVERED, started, "A110", "temp")
    result["E2"] = {
        "detect_after_last_reading_s": (fs_ts - last_reading).total_seconds() if fs_ts and last_reading else None,
        "recovered_after_restart_s": (rec_ts - started).total_seconds() if rec_ts else None,
        "other_room_decisions_during_outage": pid_count(stopped, started, exclude="A110"),
        "outage_s": (started - stopped).total_seconds(),
        "a110_hvac_during_outage_W": [
            step["rooms"]["A110"]["hvac"] for step in sim_steps
            if stopped <= step["real"] <= started
        ],
    }

    # E3: A109 HVAC actuator stopped for 40 s.
    hvac = inspect["d7065e-hvac-r008-a109-1"]
    stopped = events["E3 stop hvac-r008-a109"]
    started = parse_ts(hvac["started"])
    retry_ts, retry_text = first(RETRY, stopped - timedelta(seconds=5), "A109", "temp")
    retries = sum(
        1 for ts, text in lines
        if stopped <= ts <= started + timedelta(seconds=30)
        and (m := RETRY.search(text)) and m.group(1) == "A109" and m.group(2) == "temp"
    )
    last_confirm = last(CONFIRMED, stopped + timedelta(seconds=5), "A109", "temp")
    first_unacked = None
    for ts, text in lines:
        if last_confirm and ts > last_confirm:
            match = PID_LINE.match(text)
            if match and match.group(1) == "A109" and match.group(2) == "temp":
                first_unacked = ts
                break
    conf_ts, _ = first(CONFIRMED, started, "A109", "temp")
    result["E3"] = {
        "retry_after_first_unacked_command_s": (retry_ts - first_unacked).total_seconds() if retry_ts and first_unacked else None,
        "retries": retries,
        "confirmed_after_restart_s": (conf_ts - started).total_seconds() if conf_ts else None,
        "other_room_decisions_during_outage": pid_count(stopped, started, exclude="A109"),
        "a109_hvac_after_restart_W": [
            step["rooms"]["A109"]["hvac"] for step in sim_steps
            if started <= step["real"] <= started + timedelta(seconds=30)
        ],
    }

    # E4: decision maker killed with SIGKILL.
    killed = events["E4 kill dec"]
    last_pid = max((ts for ts, text in lines if ts < killed and PID_LINE.match(text)), default=None)
    first_pid = min((ts for ts, text in lines if ts > killed and PID_LINE.match(text)), default=None)
    result["E4"] = {
        "auto_restart": next((label for label in events if label.startswith("E4 dec after")), None),
        "manual_start": "E4 start dec (manual)" in events,
        "control_gap_s": (first_pid - last_pid).total_seconds() if first_pid and last_pid else None,
        "first_decision_after_kill_s": (first_pid - killed).total_seconds() if first_pid else None,
    }

    # E5: broker stopped for 20 s.
    broker = inspect["d7065e-mosquitto-1"]
    stopped = events["E5 stop mosquitto"]
    started = parse_ts(broker["started"])
    failsafes = sum(1 for ts, text in lines if stopped <= ts <= started + timedelta(seconds=60) and FAILSAFE.search(text))
    recovered = [ts for ts, text in lines if ts >= started and RECOVERED.search(text)]
    first_pid = min((ts for ts, text in lines if ts > started and PID_LINE.match(text)), default=None)
    result["E5"] = {
        "broker_down_s": (started - stopped).total_seconds(),
        "failsafe_entries": failsafes,
        "first_decision_after_broker_start_s": (first_pid - started).total_seconds() if first_pid else None,
        "all_recovered_after_broker_start_s": (max(recovered[:10]) - started).total_seconds() if len(recovered) >= 10 else None,
        "loops_recovered": len(recovered),
        "sim_restarts": inspect["d7065e-sim-1"]["restarts"],
        "dec_restarts": inspect["d7065e-dec-1"]["restarts"],
    }
    return result


RECEIVED_ROOM = re.compile(r"Mottaget meddelande på '0/([^/]+)/(temp|co2)/dec'")


def memory(stats_path):
    groups = defaultdict(list)
    for line in stats_path.read_text(encoding="utf-8").splitlines():
        name, usage, _cpu = line.split("\t")
        amount, unit = re.match(r"([\d.]+)(\w+)", usage.split("/")[0].strip()).groups()
        mib = float(amount) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "B": 1 / 2**20}[unit]
        service = re.sub(r"^d7065e-|-\d+$", "", name)
        kind = re.sub(r"-r\d{3}-.*$", "", service)
        groups[kind].append(mib)
    return {
        kind: {"count": len(values), "mean_MiB": statistics.mean(values), "total_MiB": sum(values)}
        for kind, values in sorted(groups.items())
    }


def write_csv(path, header, rows):
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    out = Path(sys.argv[1])
    events = parse_events(out / "events.log")
    inspect = parse_inspect(out / "inspect.txt")
    steps = parse_sim(out / "log_sim.txt")
    dec_lines = list(read_lines(out / "log_dec.txt"))
    nominal_end = events["E2 stop sensor-r009-a110"]
    nominal = [step for step in steps if step["real"] < nominal_end]
    day0 = nominal[0]["sim"].replace(hour=0, minute=0, second=0)

    lat_summary, sense, act, total = latency(nominal, dec_lines, nominal_end)
    results = {
        "window": {
            "sim_start": nominal[0]["sim"].isoformat(),
            "sim_end": nominal[-1]["sim"].isoformat(),
            "steps": len(nominal),
            "real_minutes": (nominal[-1]["real"] - nominal[0]["real"]).total_seconds() / 60,
        },
        "start_state": nominal[0]["rooms"],
        "comfort_energy": comfort_and_energy(nominal),
        "co2": co2_metrics(nominal),
        "latency": lat_summary,
        "stepping": step_interval(nominal, nominal_end),
        "nominal_failsafes": [
            (ts.isoformat(), m.group(1), m.group(2), m.group(3))
            for ts, text in dec_lines
            if ts < nominal_end and (m := FAILSAFE.search(text))
        ],
        "setpoint_changes": [
            (ts.isoformat(), float(m.group(1)), m.group(2))
            for ts, text in dec_lines
            if (m := SETPOINT.search(text)) and m.group(2) == "A107"
        ],
        "faults": faults(dec_lines, steps, inspect, events),
        "memory_20min": memory(out / "stats_20min.txt"),
    }

    rows = []
    for step in nominal:
        hour = (step["sim"] - day0).total_seconds() / 3600
        row = [f"{hour:.3f}", setpoint_at(step["sim"]), step["outside"]]
        for key in ("temp", "hvac", "co2", "vent", "occ"):
            for room in ROOMS:
                value = step["rooms"][room][key]
                row.append(f"{value / 1000:.3f}" if key == "hvac" else value)
        rows.append(row)
    header = ["hour", "setpoint", "outside"] + [
        f"{key}_{room}" for key in ("temp", "hvac", "co2", "vent", "occ") for room in ROOMS
    ]
    write_csv(DATA_DIR / "e1_rooms.csv", header, rows)
    write_csv(
        DATA_DIR / "e1_latency.csv",
        ["q", "sense_ms", "act_ms", "total_ms"],
        [
            [q / 100, f"{percentile(sense, q / 100):.1f}", f"{percentile(act, q / 100):.1f}", f"{percentile(total, q / 100):.1f}"]
            for q in range(0, 101)
        ],
    )
    (DATA_DIR / "e1_results.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
