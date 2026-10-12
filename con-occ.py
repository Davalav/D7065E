import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from time import sleep
from urllib.parse import quote

import requests


BASE = os.getenv("BUILDSIM_URL", "http://127.0.0.1:9090/")
BASE_OCC = os.getenv("OCCUPANCY_URL", "http://127.0.0.1:8081/")
DATA_DIR = Path(__file__).resolve().parent / "JSON files"
REQUEST_TIMEOUT = 10
POLL_INTERVAL_SECONDS = 0.5
SENSOR_TYPE = "occupancy"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Publish occupancy-simulator room counts to room sensors."
    )
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--timestep-minutes", type=float, default=5)
    return parser.parse_args()


def api_json(session, method, base_url, path, **kwargs):
    response = session.request(
        method,
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def sensor_id(room_name):
    return f"{room_name}-{SENSOR_TYPE}"


def ensure_sensor(session, room_name, floor):
    equipment_id = f"{SENSOR_TYPE}-{room_name}"
    current_sensor_id = sensor_id(room_name)
    try:
        api_json(
            session,
            "GET",
            BASE,
            f"api/sensors/{quote(current_sensor_id, safe='')}",
        )
        return
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code != 404:
            raise

    try:
        api_json(
            session,
            "GET",
            BASE,
            f"api/equipment/{quote(equipment_id, safe='')}",
        )
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code != 404:
            raise
        api_json(
            session,
            "POST",
            BASE,
            "api/equipment",
            json={
                "id": equipment_id,
                "name": f"Occupancy Sensor {room_name}",
                "type": "occupancy_counter",
                "category": "monitoring",
                "level": f"level{floor}",
                "room": room_name,
                "status": "running",
            },
        )

    api_json(
        session,
        "POST",
        BASE,
        f"api/equipment/{quote(equipment_id, safe='')}/sensors",
        json={
            "id": current_sensor_id,
            "name": "Occupancy",
            "type": "occupancy",
            "data_type": "text",
            "unit": "people",
            "value": "0",
        },
    )


def state_time(state):
    return datetime.fromisoformat(state["sim"]["clock"]["time"])


def room_occupancy(state, room_name, level):
    matching_rooms = [
        room
        for room in state["sim"]["rooms"]
        if room.get("name") == room_name and room.get("level") == level
    ]
    if len(matching_rooms) != 1:
        raise ValueError(
            f"Expected one occupancy-simulator entry for {room_name!r} "
            f"on {level}, found {len(matching_rooms)}"
        )
    occupants = matching_rooms[0].get("occupants")
    if isinstance(occupants, bool) or not isinstance(occupants, int) or occupants < 0:
        raise ValueError(
            f"Occupancy simulator returned an invalid count for "
            f"{room_name!r} on {level}: {occupants!r}"
        )
    return occupants


def wait_for_next_timestep(session, previous_time, timestep):
    interval_start = previous_time
    while True:
        state = api_json(session, "GET", BASE_OCC, "api/state")
        current_time = state_time(state)
        if current_time < interval_start:
            interval_start = current_time
        elif current_time - interval_start >= timestep:
            return state, current_time
        sleep(POLL_INTERVAL_SECONDS)


def main():
    args = parse_args()
    timestep = timedelta(minutes=args.timestep_minutes)
    if timestep.total_seconds() <= 0:
        raise ValueError("Timestep must be positive")
    with (DATA_DIR / "rooms.json").open("r", encoding="utf-8") as source:
        configured_rooms = json.load(source)

    session = requests.Session()
    room_floors = {
        room["name"]: str(room["floor"]) for room in configured_rooms["rooms"]
    }
    floor = room_floors.get(args.room)
    if floor is None or floor != str(args.level):
        raise ValueError(
            f"Room {args.room!r} on level {args.level!r} is not configured"
        )
    ensure_sensor(session, args.room, floor)

    state = api_json(session, "GET", BASE_OCC, "api/state")
    simulation_time = state_time(state)
    print(f"Waiting for {timestep} of occupancy-simulation time")

    try:
        while True:
            state, simulation_time = wait_for_next_timestep(
                session, simulation_time, timestep
            )
            occupants = room_occupancy(state, args.room, f"level{args.level}")
            api_json(
                session,
                "PUT",
                BASE,
                f"api/sensors/{quote(sensor_id(args.room), safe='')}/value",
                json={"data_type": "text", "value": str(occupants)},
            )
            print(
                f"{state['sim']['clock']['time']} | "
                f"{args.room}: {occupants} occupants"
            )
    except KeyboardInterrupt:
        print("\nStopping occupancy publisher.")


if __name__ == "__main__":
    main()
