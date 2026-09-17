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

co2_equipment = {
    "id": f"co2-{room}",
    "name": f"CO2 Sensor {room}",
    "type": "co2_sensor",
    "category": "monitoring",
    "level": "level0",
    "room": room,
    "status": "running"
}

response = requests.post(
    f"{BASE}api/equipment",
    json=co2_equipment,
    headers=headers
)

print(response.status_code)
print(response.text)

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

print(response.status_code)
print(response.text)