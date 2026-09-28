import requests
import pandas as pd
import time

BASE = "http://127.0.0.1:9090/"
room = "A109"

headers = {
    "Content-Type": "application/json"
}

# --------------------------------------------------
# LÄS EXCEL
# --------------------------------------------------

dfs = pd.read_excel(
    "LectureTable.xlsx",
    sheet_name=["Sheet1", "Sheet2"]
)

print(dfs["Sheet1"].head())
print(dfs["Sheet2"].head())

schedule = dfs["Sheet2"]


# --------------------------------------------------
# SKAPA OCCUPANCY EQUIPMENT
# --------------------------------------------------

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

print("Occupancy equipment:", response.status_code, response.text)


# --------------------------------------------------
# SKAPA OCCUPANCY SENSOR
# --------------------------------------------------

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

print("Occupancy sensor:", response.status_code, response.text)


# --------------------------------------------------
# SKAPA CO2 EQUIPMENT
# --------------------------------------------------

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

print("CO2 equipment:", response.status_code, response.text)


# --------------------------------------------------
# SKAPA CO2 SENSOR
# --------------------------------------------------

co2_sensor = {
    "id": f"{room}-co2",
    "name": "CO2",
    "type": "co2",
    "data_type": "text",
    "unit": "ppm",
    "value": "420"
}

response = requests.post(
    f"{BASE}api/equipment/co2-{room}/sensors",
    json=co2_sensor,
    headers=headers
)

print("CO2 sensor:", response.status_code, response.text)


# --------------------------------------------------
# STARTVÄRDEN FÖR SIMULATION
# --------------------------------------------------

simulation_time = pd.Timestamp("2026-09-21 08:00")
end_time = pd.Timestamp("2026-09-21 18:00")

occupancy = 0
co2 = 420


# --------------------------------------------------
# SIMULATION
# --------------------------------------------------

while simulation_time <= end_time:

    current_time = simulation_time.time()

    # Hitta aktivt pass för rummet
    active = schedule[
        (schedule["Klassrum"] == room) &
        (schedule["Start"] <= current_time) &
        (schedule["Slut"] > current_time)
    ]

    # Finns det ett aktivt pass?
    if not active.empty:
        lesson = active.iloc[0]["Lektion"] == "Ja"
    else:
        lesson = False


    # --------------------------------------------------
    # OCCUPANCY
    # --------------------------------------------------

    target_occupancy = 25 if lesson else 0

    # Personer kommer in gradvis
    if occupancy < target_occupancy:
        occupancy = min(
            occupancy + 5,
            target_occupancy
        )

    # Personer lämnar gradvis
    elif occupancy > target_occupancy:
        occupancy = max(
            occupancy - 5,
            target_occupancy
        )


    # --------------------------------------------------
    # CO2
    # --------------------------------------------------

    outdoor_co2 = 420

    generation = occupancy * 2
    ventilation = (co2 - outdoor_co2) * 0.05

    co2 += generation - ventilation

    # Hindra CO2 från att gå under utomhusnivån
    co2 = max(co2, outdoor_co2)


    # --------------------------------------------------
    # SKICKA OCCUPANCY TILL SIMULATORN
    # --------------------------------------------------

    occupancy_payload = {
        "data_type": "text",
        "value": str(occupancy)
    }

    occupancy_response = requests.put(
        f"{BASE}api/sensors/{room}-occupancy/value",
        json=occupancy_payload,
        headers=headers
    )


    # --------------------------------------------------
    # SKICKA CO2 TILL SIMULATORN
    # --------------------------------------------------

    co2_payload = {
        "data_type": "text",
        "value": str(round(co2, 2))
    }

    co2_response = requests.put(
        f"{BASE}api/sensors/{room}-co2/value",
        json=co2_payload,
        headers=headers
    )


    # --------------------------------------------------
    # PRINTA VAD SOM HÄNDER
    # --------------------------------------------------

    print(
        simulation_time.time(),
        "| Lesson:", lesson,
        "| Occupancy:", occupancy,
        "| CO2:", round(co2),
        "| Occ status:", occupancy_response.status_code,
        "| CO2 status:", co2_response.status_code
    )


    # --------------------------------------------------
    # GÅ FRAM 5 SIMULERADE MINUTER
    # --------------------------------------------------

    simulation_time += pd.Timedelta(minutes=5)


    # 1 riktig sekund = 5 simulerade minuter
    time.sleep(1)