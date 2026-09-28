import requests
import pandas as pd

BASE = "http://127.0.0.1:9090/"
room = "A109"

"""
go build -o buildsim ./cmd
./buildsim start --port 9090
"""

headers = {
    "Content-Type": "application/json"
}

"""
POST equipment
      ↓
occupancy-A109 skapas

POST sensor
      ↓
A109-occupancy skapas med value = 0

PUT sensor value
      ↓
A109-occupancy ändras till value = 5
"""

dfs = pd.read_excel("LectureTable.xlsx",sheet_name=["Sheet1", "Sheet2"])

print(dfs["Sheet1"].head())
print(dfs["Sheet2"].head())

schedule = dfs["Sheet2"]

row = schedule[schedule["Pass"] == 1].iloc[0]

lektion = row["Lektion"] == "Ja"

if lektion:
    occupancy = 22
else:
    occupancy = 0

print("Pass:", row["Pass"])
print("Lektion:", lektion)
print("Occupancy:", occupancy)


occupancy_equipment = {
    "id": f"occupancy-{room}",
    "name": f"Occupancy Counter {room}",
    "type": "occupancy_counter",
    "category": "monitoring",
    "level": "level0",
    "room": room,
    "status": "running"
}


# Skapar equipment-objektet
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
    "value": "4"
}

# skapar sensorn som ligger under equipmentet
response = requests.post(
    f"{BASE}api/equipment/occupancy-{room}/sensors",
    json=occupancy_sensor,
    headers=headers
)

print("Sensor:", response.status_code, response.text)

occupancy = 5

payload = {
    "data_type": "text",
    "value": str(occupancy)
}

response = requests.put(
    f"{BASE}api/sensors/{room}-occupancy/value",
    json=payload,
    headers=headers
)

print("Updated occupancy:", response.status_code, response.text)

"""
POST 1
→ skapa equipment

POST 2
→ skapa sensor med startvärde

PUT
→ ändra sensorvärdet senare
"""




# -----------------------------
# CO2
# -----------------------------
co2 = 420


co2_equipment = {
    "id": f"co2-{room}",
    "name": f"CO2 Sensor {room}",
    "type": "co2_sensor",
    "category": "monitoring",
    "level": "level0",
    "room": room,
    "status": "running"
}

# Skapar CO2-equipment
response = requests.post(
    f"{BASE}api/equipment",
    json=co2_equipment,
    headers=headers
)

print("CO2 equipment:", response.status_code, response.text)


co2_sensor = {
    "id": f"{room}-co2",
    "name": "CO2",
    "type": "co2",
    "data_type": "text",
    "unit": "ppm",
    "value": str(co2)
}

# Skapar CO2-sensorn under equipmentet
response = requests.post(
    f"{BASE}api/equipment/co2-{room}/sensors",
    json=co2_sensor,
    headers=headers
)


print("CO2 sensor:", response.status_code, response.text)

def step(BASE, curco2, volume, deltaT, occupancy):

    # Enkel testmodell:
    # varje person ökar CO2 med 10 ppm per steg
    curco2 += occupancy * 10

    payload = {
        "data_type": "text",
        "value": str(round(curco2, 2))
    }

    response = requests.put(
        f"{BASE}api/sensors/{room}-co2/value",
        json=payload,
        headers=headers
    )

    print("Updated CO2:", response.status_code, response.text)
    print("CO2:", curco2)

    return curco2

payload = {
    "data_type": "text",
    "value": str(co2)
}

# Uppdaterar CO2-sensorns värde
response = requests.put(
    f"{BASE}api/sensors/{room}-co2/value",
    json=payload,
    headers=headers
)

print("Updated CO2:", response.status_code, response.text)

co2 = step(BASE, co2, 100, 60, occupancy)