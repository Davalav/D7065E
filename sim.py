import argparse
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
from time import sleep

import requests


BASE = "http://127.0.0.1:9090/"
DATA_DIR = Path(__file__).resolve().parent / "JSON files"
REQUEST_TIMEOUT = 10
ROOM_HEIGHT_METERS = 3.0
AIR_DENSITY_KG_PER_M3 = 1.225
AIR_HEAT_CAPACITY_J_PER_KG_K = 1000.0
EXTERIOR_WALL_U_VALUE_W_PER_M2_K = 0.25
VENTILATION_AIR_CHANGES_PER_HOUR = 0.5
THERMAL_MASS_CAPACITY_J_PER_M2_K = 165_000.0
AIR_MASS_COUPLING_W_PER_M2_K = 8.0
DEFAULT_OCCUPANTS_PER_LECTURE = 20
SENSIBLE_HEAT_PER_OCCUPANT_W = 75.0


def parse_args():
    parser = argparse.ArgumentParser(description="Simulate room temperatures.")
    parser.add_argument(
        "selection",
        nargs="?",
        default="0",
        help="floor number, or 'Alfa' to simulate all configured rooms",
    )
    parser.add_argument("room", nargs="?", default="A109", help="room name")
    parser.add_argument("--base-url", default=BASE, help="building simulator API URL")
    parser.add_argument("--start", default="2026-09-21T08:00")
    parser.add_argument("--end", default="2026-09-21T18:00")
    parser.add_argument("--timestep-minutes", type=float, default=15)
    #parser.add_argument("--heater-watts", type=float, default=500)
    parser.add_argument("--occupants-per-lecture", type=int, default=DEFAULT_OCCUPANTS_PER_LECTURE)
    parser.add_argument("--delay-seconds", type=float, default=1)
    return parser.parse_args()


def load_json(path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def api_json(session, method, base_url, path, **kwargs):
    response = session.request(
        method,
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def prepare_weather(weather_rows):
    weather_by_day = {}
    for row in weather_rows:
        day = row["Day"]
        observed_at = time.fromisoformat(row["Time"])
        temperature = float(row["Temperature"])
        weather_by_day.setdefault(day, []).append((observed_at, temperature))

    for observations in weather_by_day.values():
        observations.sort(key=lambda observation: observation[0])
    return weather_by_day


def outside_temperature_at(weather_by_day, timestamp):
    observations = weather_by_day.get(timestamp.strftime("%A"))
    if not observations:
        raise ValueError(f"No weather observations for {timestamp.strftime('%A')}")

    current_time = timestamp.time()
    if current_time <= observations[0][0]:
        return observations[0][1]
    if current_time >= observations[-1][0]:
        return observations[-1][1]

    for (before_time, before_temp), (after_time, after_temp) in zip(
        observations, observations[1:]
    ):
        if before_time <= current_time <= after_time:
            span = (
                datetime.combine(timestamp.date(), after_time)
                - datetime.combine(timestamp.date(), before_time)
            ).total_seconds()
            elapsed = (
                datetime.combine(timestamp.date(), current_time)
                - datetime.combine(timestamp.date(), before_time)
            ).total_seconds()
            fraction = elapsed / span
            return before_temp + fraction * (after_temp - before_temp)

    raise ValueError(f"Could not interpolate weather at {timestamp}")


def lecture_is_active(schedule, room, timestamp):
    current_time = timestamp.time()
    return any(
        row["Day"] == timestamp.strftime("%A")
        and row["Classroom"] == room
        and row["Lecture"]
        and time.fromisoformat(row["Start"]) <= current_time < time.fromisoformat(row["End"])
        for row in schedule
    )


def simulate_step(
    air_temperature,
    mass_temperature,
    volume_m3,
    floor_area_m2,
    exterior_wall_length_m,
    outside_temperature,
    setpoint,
    heater_max_watts,
    duration_seconds,
    internal_gains_watts=0.0,
):
    if volume_m3 <= 0 or floor_area_m2 <= 0:
        raise ValueError("Room volume and floor area must be positive")
    if duration_seconds <= 0:
        raise ValueError("Timestep duration must be positive")

    air_capacity = (
        AIR_DENSITY_KG_PER_M3 * volume_m3 * AIR_HEAT_CAPACITY_J_PER_KG_K
    )
    mass_capacity = floor_area_m2 * THERMAL_MASS_CAPACITY_J_PER_M2_K
    exterior_wall_area = max(0.0, exterior_wall_length_m) * ROOM_HEIGHT_METERS
    fabric_conductance = EXTERIOR_WALL_U_VALUE_W_PER_M2_K * exterior_wall_area
    ventilation_conductance = (
        AIR_DENSITY_KG_PER_M3
        * AIR_HEAT_CAPACITY_J_PER_KG_K
        * volume_m3
        * VENTILATION_AIR_CHANGES_PER_HOUR
        / 3600
    )
    air_mass_conductance = floor_area_m2 * AIR_MASS_COUPLING_W_PER_M2_K
    total_outside_conductance = fabric_conductance + ventilation_conductance

    # Substeps keep this explicit two-node heat balance stable at larger API timesteps.
    substep_count = max(1, int(duration_seconds // 60) + 1)
    substep_seconds = duration_seconds / substep_count
    for _ in range(substep_count):
        outside_loss = total_outside_conductance * (
            air_temperature - outside_temperature
        )
        mass_exchange = air_mass_conductance * (mass_temperature - air_temperature)
        required_heating = (
            (setpoint - air_temperature) * air_capacity / substep_seconds
            - mass_exchange
            - internal_gains_watts
            + outside_loss
        )
        #heater_watts = (
        #    min(heater_max_watts, max(0.0, required_heating))
        #    if air_temperature < setpoint
        #    else 0.0
        #)
        heater_watts = heater_max_watts
        air_temperature += (
            heater_watts
            + internal_gains_watts
            - outside_loss
            + mass_exchange
        ) * substep_seconds / air_capacity
        mass_temperature -= (
            mass_exchange * substep_seconds / mass_capacity
        )

    return air_temperature, mass_temperature


def main():
    args = parse_args()
    start_time = datetime.fromisoformat(args.start)
    end_time = datetime.fromisoformat(args.end)
    timestep = timedelta(minutes=args.timestep_minutes)
    if end_time < start_time:
        raise ValueError("End time must be at or after start time")
    if timestep.total_seconds() <= 0:
        raise ValueError("Timestep must be positive")
    #if args.heater_watts < 0 or args.occupants_per_lecture < 0:
    #    raise ValueError("Heater power and occupancy must be non-negative")
    if args.delay_seconds < 0:
        raise ValueError("Delay must be non-negative")

    lecture_data = load_json(DATA_DIR / "Lectures.json")
    weather_data = load_json(DATA_DIR / "Weather.json")
    room_data = load_json(DATA_DIR / "rooms.json")
    schedule = lecture_data["schedule"]
    weather_by_day = prepare_weather(weather_data["weather"])
    configured_rooms = {str(room["name"]): room for room in room_data["rooms"]}

    if args.selection == "Alfa":
        selected_rooms = list(room_data["rooms"])
    else:
        room = configured_rooms.get(args.room)
        if room is None:
            raise ValueError(f"Room {args.room!r} is not present in {DATA_DIR / 'rooms.json'}")
        if str(room["floor"]) != args.selection:
            raise ValueError(
                f"Room {args.room!r} is on floor {room['floor']}, not {args.selection}"
            )
        selected_rooms = [room]

    session = requests.Session()
    rooms = []
    activated_equipment = []
    
    floor_data= {}
    
    try:
        for configured_room in selected_rooms:
            room_name = configured_room["name"]
            floor = configured_room["floor"]
            if floor not in floor_data:
                floor_data[floor] = api_json(
                session,
                "GET",
                args.base_url,
                f"api/building/floors/level{floor}",
            )
            floor_room = next(
                (item for item in floor_data[floor]["rooms"] if item["name"] == room_name),
                None,
            )
            if floor_room is None:
                raise ValueError(
                    f"Room {room_name!r} not found on floor {floor} in building API"
                )

            sensor = api_json(
                session, "GET", args.base_url, f"api/sensors/{room_name}-temp"
            )
            air_temperature = float(sensor["value"])
            equipment_path = f"api/equipment/hvac-{room_name}"
            equipment = api_json(session, "GET", args.base_url, equipment_path)
            activated_equipment.append((room_name, equipment_path, equipment))
            equipment["status"] = "running"
            api_json(
                session,
                "PUT",
                args.base_url,
                equipment_path,
                json=equipment,
            )
            rooms.append(
                {
                    "name": room_name,
                    "area": float(floor_room["area"]),
                    "wall_length": float(configured_room["walls"]),
                    "air_temperature": air_temperature,
                    "mass_temperature": air_temperature,
                }
            )

        print(f"Simulating {len(rooms)} room(s) from {start_time} to {end_time}")
        simulation_time = start_time
        while simulation_time <= end_time:
            outside_temperature = outside_temperature_at(weather_by_day, simulation_time)
            print(
                f"{simulation_time:%A %H:%M} | "
                f"Outside temperature: {outside_temperature:.1f} °C"
            )

            for room in rooms:
                occupied = lecture_is_active(
                    schedule, room["name"], simulation_time
                )
                internal_gains = (
                    args.occupants_per_lecture * SENSIBLE_HEAT_PER_OCCUPANT_W
                    if occupied
                    else 0.0
                )
                
                room["air_temperature"], room["mass_temperature"] = simulate_step(
                    air_temperature=room["air_temperature"],
                    mass_temperature=room["mass_temperature"],
                    volume_m3=room["area"] * ROOM_HEIGHT_METERS,
                    floor_area_m2=room["area"],
                    exterior_wall_length_m=room["wall_length"],
                    outside_temperature=outside_temperature,
                    setpoint=float(
                        api_json(
                            session,
                            "GET",
                            args.base_url,
                            f"api/actuators/{room['name']}-set",
                        )["state"]
                    ),
                    heater_max_watts=float(
                        api_json(
                            session,
                            "GET",
                            args.base_url,
                            f"api/actuators/{room['name']}-watt",
                        )["state"]
                    ),
                    duration_seconds=timestep.total_seconds(),
                    internal_gains_watts=internal_gains,
                )
                api_json(
                    session,
                    "PUT",
                    args.base_url,
                    f"api/sensors/{room['name']}-temp/value",
                    json={
                        "data_type": "text",
                        "value": str(round(room["air_temperature"], 2)),
                    },
                )
                #print(f"{room['name']}: {room['air_temperature']:.2f} °C"f"{' (lecture)' if occupied else ''}")

            simulation_time += timestep
            if args.delay_seconds:
                sleep(args.delay_seconds)
    finally:
        cleanup_errors = []
        for room_name, equipment_path, equipment in activated_equipment:
            try:
                equipment["status"] = "stopped"
                api_json(
                    session,
                    "PUT",
                    args.base_url,
                    equipment_path,
                    json=equipment,
                )
            except requests.RequestException as error:
                cleanup_errors.append(f"{room_name}: {error}")
        if cleanup_errors:
            print(
                "Failed to stop HVAC for " + "; ".join(cleanup_errors),
                file=sys.stderr,
            )
            if sys.exc_info()[0] is None:
                raise RuntimeError("Could not stop all activated HVAC equipment")


if __name__ == "__main__":
    main()
