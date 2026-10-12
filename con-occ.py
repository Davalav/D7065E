import argparse
from datetime import datetime, time, timedelta
import json
from pathlib import Path
from time import sleep

import requests


BASE = "http://127.0.0.1:9090/"
BASE_OCC = "http://127.0.0.1:8081/"
DATA_DIR = Path(__file__).resolve().parent / "JSON files"
REQUEST_TIMEOUT = 10
POLL_INTERVAL_SECONDS = 0.5
DEFAULT_OCCUPANTS_PER_LECTURE = 20


def parse_args():
    parser = argparse.ArgumentParser(
        description="Publish lecture-based room occupancy to BuildSim."
    )
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


def lecture_occupancy(lecture_data, configured_rooms, timestamp, occupants_per_lecture):
    sessions = {
        session["Session"]: session for session in lecture_data["sessions"]
    }
    rooms = {
        room["name"]: str(room["floor"]) for room in configured_rooms["rooms"]
    }
    scheduled_rooms = {row["Classroom"] for row in lecture_data["schedule"]}
    occupancy = {
        f"level{rooms[room_name]}/{room_name}": {"persons": [], "aliens": []}
        for room_name in scheduled_rooms
        if room_name in rooms
    }
    missing_rooms = scheduled_rooms - rooms.keys()
    if missing_rooms:
        raise ValueError(
            f"Lecture rooms missing from rooms.json: {', '.join(sorted(missing_rooms))}"
        )

    for row in lecture_data["schedule"]:
        if row["Day"] != timestamp.strftime("%A"):
            continue

        session = sessions[row["Session"]]
        start = time.fromisoformat(session["StartTime"])
        end = time.fromisoformat(session["EndTime"])
        current_time = timestamp.time().replace(tzinfo=None)
        active = row["Lecture"] and start <= current_time < end
        room_key = f"level{rooms[row['Classroom']]}/{row['Classroom']}"
        room_occupants = occupancy.setdefault(
            room_key, {"persons": [], "aliens": []}
        )["persons"]

        if active:
            room_occupants.extend(
                {
                    "id": f"lecture-{row['Classroom']}-{index + 1}",
                    "name": f"Student {index + 1}",
                }
                for index in range(occupants_per_lecture)
            )

    return occupancy


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
    state = api_json(session, "GET", BASE_OCC, "api/state")
    simulation_time = state_time(state)
    print(f"Waiting for {timestep} of occupancy-simulation time")

    try:
        while True:
            state, simulation_time = wait_for_next_timestep(
                session, simulation_time, timestep
            )
            updated_occupancy = lecture_occupancy(
                lecture_data,
                configured_rooms,
                simulation_time,
                args.occupants_per_lecture,
            )
            current_occupancy = api_json(
                session, "GET", BASE, "api/occupancy"
            )
            current_occupancy.update(updated_occupancy)
            api_json(
                session,
                "PUT",
                BASE,
                "api/occupancy",
                json=current_occupancy,
            )
            active_rooms = sum(
                bool(room["persons"]) for room in updated_occupancy.values()
            )
            print(
                f"{state['sim']['clock']['time']} | "
                f"{active_rooms} lecture room(s) occupied"
            )
    except KeyboardInterrupt:
        print("\nStopping occupancy publisher.")


if __name__ == "__main__":
    main()
