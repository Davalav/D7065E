"""Enable the first N rooms of rooms.json that resolve cleanly, for scaling runs.

    python report/experiments/select_rooms.py <N>      (run from the repo root)

A room is eligible when BuildSim lists it as a room on level0 and the occupancy
simulator has exactly one level0 entry with that name; otherwise its occupancy
publisher would crash-loop. Rooms enabled now are kept. Needs both systems
running on their default ports.
"""
import json
import sys
from pathlib import Path
from urllib.request import urlopen


ROOMS_PATH = Path("JSON files") / "rooms.json"


def get(url):
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def main():
    wanted = int(sys.argv[1])
    floor = get("http://127.0.0.1:9090/api/building/floors/level0")
    state = get("http://127.0.0.1:8081/api/state")
    buildsim_rooms = {room["name"] for room in floor["rooms"] if room.get("type") == "room"}
    occupancy_counts = {}
    for room in state["sim"]["rooms"]:
        if room["level"] == "level0":
            occupancy_counts[room["name"]] = occupancy_counts.get(room["name"], 0) + 1

    data = json.loads(ROOMS_PATH.read_text(encoding="utf-8"))
    # Rooms enabled now come first, so each larger run is a superset of the last.
    ordered = sorted(data["rooms"], key=lambda room: not room.get("simulate", True))
    eligible = [
        room["name"] for room in ordered
        if room["name"] in buildsim_rooms and occupancy_counts.get(room["name"]) == 1
    ]
    chosen = set(eligible[:wanted])
    for room in data["rooms"]:
        room["simulate"] = room["name"] in chosen
    ROOMS_PATH.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"{len(eligible)} of {len(data['rooms'])} rooms eligible; enabled {len(chosen)}")


if __name__ == "__main__":
    main()
