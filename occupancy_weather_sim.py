import requests
import pandas as pd
import time
import json

BASE = "http://127.0.0.1:9090/"
room = "A109"

headers = {
    "Content-Type": "application/json"
}

# --------------------------------------------------
# LÄS JSON
# --------------------------------------------------

with open("JSON files/Lectures.json", "r", encoding="utf-8") as f:
    lecture_data = json.load(f)

with open("JSON files/Weather.json", "r", encoding="utf-8") as f:
    weather_data = json.load(f)

schedule = lecture_data["schedule"]
weather = weather_data["weather"]

print("Schedule loaded:")
print(schedule[:3])

print("\nWeather loaded:")
print(weather[:3])

# --------------------------------------------------
# STARTVÄRDEN FÖR SIMULATION
# --------------------------------------------------

simulation_time = pd.Timestamp("2026-09-21 08:00")
end_time = pd.Timestamp("2026-09-21 18:00")

occupancy = 0
co2 = 420

timestep = pd.Timedelta(minutes=5)

# --------------------------------------------------
# SIMULATION
# --------------------------------------------------

while simulation_time <= end_time:

    current_day = simulation_time.day_name()
    current_time = simulation_time.strftime("%H:%M:%S")

    # --------------------------------------------------
    # HITTA AKTIV LEKTION
    # --------------------------------------------------

    active = [
        row for row in schedule
        if row["Classroom"] == room
        and row["Day"] == current_day
        and row["Start"] <= current_time
        and row["End"] > current_time
    ]

    if active:
        lesson = active[0]["Lecture"]
    else:
        lesson = False

    # --------------------------------------------------
    # HITTA AKTUELL UTOMHUSTEMPERATUR
    # --------------------------------------------------

    weather_today = [
        row for row in weather
        if row["Day"] == current_day
    ]

    current_weather = None

    for row in weather_today:
        if row["Time"] <= current_time:
            current_weather = row
        else:
            break

    if current_weather is None and weather_today:
        current_weather = weather_today[0]

    if current_weather:
        outside_temperature = current_weather["Temperature"]
    else:
        outside_temperature = None

    # --------------------------------------------------
    # OCCUPANCY
    # --------------------------------------------------

    target_occupancy = 25 if lesson else 0

    if occupancy < target_occupancy:
        occupancy = min(
            occupancy + 5,
            target_occupancy
        )

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
    co2 = max(co2, outdoor_co2)

    # --------------------------------------------------
    # SKICKA OCCUPANCY
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
    # SKICKA CO2
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
    # PRINTA SIMULATIONEN
    # --------------------------------------------------

    print(
        current_day,
        current_time,
        "| Outside temp:", outside_temperature,
        "| Lesson:", lesson,
        "| Occupancy:", occupancy,
        "| CO2:", round(co2),
        "| Occ:", occupancy_response.status_code,
        "| CO2 status:", co2_response.status_code
    )

    simulation_time += timestep

    time.sleep(1)