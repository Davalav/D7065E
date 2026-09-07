import requests

BASE = "http://127.0.0.1:9090"

# HVAC
hvac = {
    "id": "hvac-A109",
    "name": "HVAC A109",
    "type": "ac_unit",
    "category": "hvac",
    "level": "level0",
    "room": "A109",
    "status": "running"
}

# CO2
co2_equipment = {
    "id": "co2-A109",
    "name": "CO2 Sensor A109",
    "type": "co2_sensor",
    "category": "monitoring",
    "level": "level0",
    "room": "A109",
    "status": "running"
}

# Occupancy counter
occupancy_equipment = {
    "id": "occupancy-A109",
    "name": "Occupancy Counter A109",
    "type": "occupancy_counter",
    "category": "monitoring",
    "level": "level0",
    "room": "A109",
    "status": "running"
}

# Temperature sensor
temperature_equipment = {
    "id": "temp-A109",
    "name": "Temperature Sensor A109",
    "type": "temperature_sensor",
    "category": "monitoring",
    "level": "level0",
    "room": "A109",
    "status": "running"
}

# Skapa all equipment
for equipment in [
    hvac,
    co2_equipment,
    occupancy_equipment,
    temperature_equipment
]:
    response = requests.post(
        BASE + "/api/equipment",
        json=equipment
    )

    print(
        equipment["id"],
        response.status_code,
        response.text
    )