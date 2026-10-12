import argparse
from datetime import datetime, time, timedelta
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
DEFAULT_OCCUPANTS_PER_LECTURE = 20
SENSOR_TYPE = "occupancy"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Publish lecture-based room occupancy to room sensors."
    )
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--timestep-minutes", type=float, default=5)
    parser.add_argument(
        "--occupants-per-lecture",
        type=int,
        default=DEFAULT_OCCUPANTS_PER_LECTURE,
    )
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
        api_json(session, "GET", BASE, f"api/sensors/{quote(current_sensor_id, safe='')}")
        return
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code != 404:
            raise

    try:
        api_json(session, "GET", BASE, f"api/equipment/{quote(equipment_id, safe='')}")
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


def lecture_occupancy(lecture_data, room_name, timestamp, occupants_per_lecture):
    sessions = {
        session["Session"]: session for session in lecture_data["sessions"]
    }
    occupants = 0

    for row in lecture_data["schedule"]:
        if row["Classroom"] != room_name or row["Day"] != timestamp.strftime("%A"):
            continue

        session = sessions[row["Session"]]
        start = time.fromisoformat(session["StartTime"])
        end = time.fromisoformat(session["EndTime"])
        current_time = timestamp.time().replace(tzinfo=None)
        active = row["Lecture"] and start <= current_time < end
        if active:
            occupants += occupants_per_lecture

    return occupants


def main():
    args = parse_args()
    timestep = timedelta(minutes=args.timestep_minutes)
    if timestep.total_seconds() <= 0:
        raise ValueError("Timestep must be positive")
    if args.occupants_per_lecture < 0:
        raise ValueError("Occupants per lecture must be non-negative")

    with (DATA_DIR / "Lectures.json").open("r", encoding="utf-8") as source:
        lecture_data = json.load(source)
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
            occupants = lecture_occupancy(
                lecture_data,
                args.room,
                simulation_time,
                args.occupants_per_lecture,
            )
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
