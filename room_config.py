import json
from pathlib import Path


ROOMS_PATH = Path(__file__).resolve().parent / "JSON files" / "rooms.json"


def load_rooms(path=ROOMS_PATH):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)["rooms"]


def is_simulated(room):
    return room.get("simulate", True)


def load_simulated_rooms(path=ROOMS_PATH):
    rooms = [room for room in load_rooms(path) if is_simulated(room)]
    if not rooms:
        raise ValueError(f'No rooms in {path.name} have "simulate": true')
    return rooms
