import requests

BASE = "http://127.0.0.1:9090"

# 1. Skapa equipment
equipment = {
    "id": "hvac-A109",
    "name": "HVAC A109",
    "type": "ac_unit",
    "category": "hvac",
    "level": "level0",
    "room": "A109",
    "status": "running"
}

response = requests.post(
    f"{BASE}/api/equipment",
    json=equipment,
    timeout=5
)

print("Equipment:", response.status_code, response.text)


# 2. Skapa sensor
sensor = {
    "id": "A109-temp",
    "name": "Temperature",
    "type": "temperature",
    "data_type": "text",
    "unit": "°C",
    "value": "18.0"
}

response = requests.post(
    f"{BASE}/api/equipment/hvac-A109/sensors",
    json=sensor,
    timeout=5
)

print("Sensor:", response.status_code, response.text)


# 3. Skapa actuator
actuator = {
    "id": "A109-set",
    "name": "Setpoint",
    "type": "setpoint",
    "state": "21"
}

response = requests.post(
    f"{BASE}/api/equipment/hvac-A109/actuators",
    json=actuator,
    timeout=5
)

print("Actuator:", response.status_code, response.text)