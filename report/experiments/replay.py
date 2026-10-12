"""Offline replay of experiment E1 through the production physics and PID code.

    python replay.py            # reads ../data/e1_rooms.csv, writes ../data/replay_*.{csv,json}

The occupancy and outside temperature measured in E1 are fed, step by step,
through con-sim.py's simulate_step/simulate_co2_step and con-dec.py's
PIDRegulator with the deployed gains, the same one-step actuation lag, and the
same sensor noise. Scenarios:

  deployed     21/17 °C schedule, room area as con-sim reads it from BuildSim
  constant21   baseline without night setback
  area_fixed   21/17 °C schedule, BuildSim plan units² converted to m² (× 0.25)
"""
import csv
import importlib.util
import json
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ROOMS = ["A107", "A108", "A109", "A110", "A111"]
# GET /api/building/floors/level0 "area" (plan units²; 0.5 m per unit).
BUILDSIM_AREA = {"A107": 489.8, "A108": 491.5, "A109": 751.8, "A110": 496.6, "A111": 510.2}
M2_PER_UNIT2 = 0.25
STEP_SECONDS = 300
REAL_SECONDS_PER_STEP = 5  # OCCUPANCY_FACTOR 60: the PID integrates real time


def load(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


con_sim = load("con_sim", "con-sim.py")
con_dec = load("con_dec", "con-dec.py")
WALLS = {room["name"]: room["walls"] for room in json.loads((ROOT / "JSON files" / "rooms.json").read_text(encoding="utf-8"))["rooms"]}


def schedule(hour):
    return 17.0 if hour % 24 >= 18 or hour % 24 < 6 else 21.0


def run(rows, room, area, setpoint_rule, seed):
    rng = random.Random(seed)
    temp_cfg = con_dec.CONTROLLER_SETTINGS["temp"]
    co2_cfg = con_dec.CONTROLLER_SETTINGS["co2"]
    heat = con_dec.PIDRegulator(temp_cfg["setpoint"], temp_cfg["kp"], temp_cfg["ki"], temp_cfg["kd"], temp_cfg["max_watts"])
    vent = con_dec.PIDRegulator(co2_cfg["setpoint"], co2_cfg["kp"], co2_cfg["ki"], co2_cfg["kd"], co2_cfg["max_watts"], reverse_action=True)
    first = rows[0]
    air = mass = float(first[f"temp_{room}"])
    co2 = float(first[f"co2_{room}"])
    watts = float(first[f"hvac_{room}"]) * 1000
    vent_watts = float(first[f"vent_{room}"])
    trace = []
    for index, row in enumerate(rows[1:], start=1):
        occupants = int(row[f"occ_{room}"])
        air, mass = con_sim.simulate_step(
            air_temperature=air, mass_temperature=mass, volume_m3=area * con_sim.ROOM_HEIGHT_METERS,
            floor_area_m2=area, exterior_wall_length_m=WALLS[room], outside_temperature=float(row["outside"]),
            setpoint=21, heater_max_watts=watts, duration_seconds=STEP_SECONDS,
            internal_gains_watts=occupants * con_sim.SENSIBLE_HEAT_PER_OCCUPANT_W,
        )
        co2 = con_sim.simulate_co2_step(co2, occupants, vent_watts, area * con_sim.ROOM_HEIGHT_METERS, STEP_SECONDS)
        reading = air + rng.gauss(0, 0.2)
        co2_reading = max(con_sim.OUTDOOR_CO2_PPM, co2 + rng.gauss(0, 10))
        hour = float(row["hour"])
        heat.setpoint = setpoint_rule(hour)
        now = index * REAL_SECONDS_PER_STEP
        trace.append((hour, air, watts, co2, vent_watts, occupants, heat.setpoint))
        # The command computed from this reading is what the next step applies.
        watts = heat.update(reading, now=now)
        vent_watts = vent.update(co2_reading, now=now)
    return trace


def summarise(trace):
    energy = sum(watts * STEP_SECONDS for _, _, watts, *_ in trace) / 3.6e6
    reached = next((hour for hour, air, *_, sp in trace if sp == 21 and air >= 20.5), None)
    day = [(air, sp) for hour, air, *_, sp in trace if sp == 21 and reached is not None and hour >= reached]
    occupied = [co2 for _, _, _, co2, _, occ, _ in trace if occ > 0]
    return {
        "energy_kWh": energy,
        "hours_to_20.5C": None if reached is None else reached - trace[0][0],
        "day_in_band_pct": 100 * sum(abs(air - sp) <= 1 for air, sp in day) / len(day) if day else None,
        "co2_peak_ppm": max(co2 for _, _, _, co2, *_ in trace),
        "occupied_above_1000_pct": 100 * sum(c > 1000 for c in occupied) / len(occupied) if occupied else None,
    }


def main():
    with (DATA_DIR / "e1_rooms.csv").open(encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    results = {}
    traces = {}
    for seed, room in enumerate(ROOMS):
        scenarios = {
            "deployed": run(rows, room, BUILDSIM_AREA[room], schedule, seed),
            "constant21": run(rows, room, BUILDSIM_AREA[room], lambda hour: 21.0, seed),
            "area_fixed": run(rows, room, BUILDSIM_AREA[room] * M2_PER_UNIT2, schedule, seed),
        }
        traces[room] = scenarios
        measured = [float(row[f"temp_{room}"]) for row in rows[1:]]
        replayed = [air for _, air, *_ in scenarios["deployed"]]
        rmse = (sum((a - b) ** 2 for a, b in zip(measured, replayed)) / len(measured)) ** 0.5
        results[room] = {name: summarise(trace) for name, trace in scenarios.items()}
        results[room]["deployed_vs_measured_temp_rmse_C"] = rmse
        results[room]["measured_energy_kWh"] = sum(float(row[f"hvac_{room}"]) * 1000 * STEP_SECONDS for row in rows[1:]) / 3.6e6

    totals = {
        name: sum(results[room][name]["energy_kWh"] for room in ROOMS)
        for name in ("deployed", "constant21", "area_fixed")
    }
    totals["measured"] = sum(results[room]["measured_energy_kWh"] for room in ROOMS)
    results["totals_kWh"] = totals
    results["setback_saving_pct"] = 100 * (1 - totals["deployed"] / totals["constant21"])

    with (DATA_DIR / "replay_traces.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["hour"] + [f"{name}_{field}_{room}" for room in ("A108",) for name in ("deployed", "constant21", "area_fixed") for field in ("temp", "kw", "co2")])
        for index in range(len(traces["A108"]["deployed"])):
            row = [f"{traces['A108']['deployed'][index][0]:.3f}"]
            for name in ("deployed", "constant21", "area_fixed"):
                _, air, watts, co2, *_ = traces["A108"][name][index]
                row += [f"{air:.2f}", f"{watts / 1000:.3f}", f"{co2:.1f}"]
            writer.writerow(row)
    (DATA_DIR / "replay_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
