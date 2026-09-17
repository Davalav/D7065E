import requests

BASE = "http://127.0.0.1:9090/"
room = "A109"

"""
go build -o buildsim ./cmd
./buildsim start --port 9090
"""

headers = {
    "Content-Type": "application/json"
}

occupancy_equipment = {
    "id": f"occupancy-{room}",
    "name": f"Occupancy Counter {room}",
    "type": "occupancy_counter",
    "category": "monitoring",
    "level": "level0",
    "room": room,
    "status": "running"
}

response = requests.post(
    f"{BASE}api/equipment",
    json=occupancy_equipment,
    headers=headers
)

print("Equipment:", response.status_code, response.text)


occupancy_sensor = {
    "id": f"{room}-occupancy",
    "name": "Occupancy",
    "type": "occupancy",
    "data_type": "text",
    "unit": "people",
    "value": "0"
}

response = requests.post(
    f"{BASE}api/equipment/occupancy-{room}/sensors",
    json=occupancy_sensor,
    headers=headers
)

print("Sensor:", response.status_code, response.text)