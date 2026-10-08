# En temp sim
import time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import argparse
import paho.mqtt.publish as publish
import json
import requests
from datetime import datetime, time, timedelta
from pathlib import Path


BASE="http://127.0.0.1:9090/"
BASE_OCC="http://127.0.0.1:8081/"
headers = {'Content-Type': 'application/json'}

default_set_temp=21
default_wattage=300
equipments = {
    "hvac": {
        "id": "hvac-",
        "name": "HVAC ",
        "type": "ac_unit",
        "category": "hvac",      
    },
    "set_temp":{
        "id":"-set",
        "name":"Setpoint",
        "type":"setpoint",
        "state":f"{default_set_temp}"},
    "watt":{    
        "id":"-watt",
        "name":"Wattage",
        "type":"wattage",
        "state":f"{default_wattage}"
    }
}

DATA_DIR = Path(__file__).resolve().parent / "JSON files"
REQUEST_TIMEOUT = 10
ROOM_HEIGHT_METERS = 3.0
AIR_DENSITY_KG_PER_M3 = 1.225
AIR_HEAT_CAPACITY_J_PER_KG_K = 1000.0
EXTERIOR_WALL_U_VALUE_W_PER_M2_K = 0.25
VENTILATION_AIR_CHANGES_PER_HOUR = 0.5
THERMAL_MASS_CAPACITY_J_PER_M2_K = 165_000.0
AIR_MASS_COUPLING_W_PER_M2_K = 8.0
DEFAULT_OCCUPANTS_PER_LECTURE = 20
SENSIBLE_HEAT_PER_OCCUPANT_W = 75.0

def parse_args():
    parser = argparse.ArgumentParser(description="Simulate room temperatures.")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--timestep-minutes", type=float, default=15)
    #parser.add_argument("--heater-watts", type=float, default=500)
    parser.add_argument("--occupants-per-lecture", type=int, default=DEFAULT_OCCUPANTS_PER_LECTURE)
    parser.add_argument("--temperature", type=float, default=25)
    return parser.parse_args()

def load_json(path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)

def prepare_weather(weather_rows):
    weather_by_day = {}
    for row in weather_rows:
        day = row["Day"]
        observed_at = time.fromisoformat(row["Time"])
        temperature = float(row["Temperature"])
        weather_by_day.setdefault(day, []).append((observed_at, temperature))

    for observations in weather_by_day.values():
        observations.sort(key=lambda observation: observation[0])
    return weather_by_day


def outside_temperature_at(weather_by_day, timestamp):
    observations = weather_by_day.get(timestamp.strftime("%A"))
    if not observations:
        raise ValueError(f"No weather observations for {timestamp.strftime('%A')}")

    current_time = timestamp.time()
    if current_time <= observations[0][0]:
        return observations[0][1]
    if current_time >= observations[-1][0]:
        return observations[-1][1]

    for (before_time, before_temp), (after_time, after_temp) in zip(
        observations, observations[1:]
    ):
        if before_time <= current_time <= after_time:
            span = (
                datetime.combine(timestamp.date(), after_time)
                - datetime.combine(timestamp.date(), before_time)
            ).total_seconds()
            elapsed = (
                datetime.combine(timestamp.date(), current_time)
                - datetime.combine(timestamp.date(), before_time)
            ).total_seconds()
            fraction = elapsed / span
            return before_temp + fraction * (after_temp - before_temp)

    raise ValueError(f"Could not interpolate weather at {timestamp}")


def lecture_is_active(schedule, sessions, room, timestamp):
    current_time = timestamp.time()
    return any(
        row["Day"] == timestamp.strftime("%A")
        and row["Classroom"] == room
        and row["Lecture"]
        #and time.fromisoformat(row["Start"]) <= current_time < time.fromisoformat(row["End"])
        and time.fromisoformat(sessions[row["Session"]-1]["StartTime"]) <= current_time < time.fromisoformat(sessions[row["Session"]-1]["EndTime"])
        for row in schedule
    )


def simulate_step(
    air_temperature,
    mass_temperature,
    volume_m3,
    floor_area_m2,
    exterior_wall_length_m,
    outside_temperature,
    setpoint,
    heater_max_watts,
    duration_seconds,
    internal_gains_watts=0.0,
):
    if volume_m3 <= 0 or floor_area_m2 <= 0:
        raise ValueError("Room volume and floor area must be positive")
    if duration_seconds <= 0:
        raise ValueError("Timestep duration must be positive")

    air_capacity = (
        AIR_DENSITY_KG_PER_M3 * volume_m3 * AIR_HEAT_CAPACITY_J_PER_KG_K
    )
    mass_capacity = floor_area_m2 * THERMAL_MASS_CAPACITY_J_PER_M2_K
    exterior_wall_area = max(0.0, exterior_wall_length_m) * ROOM_HEIGHT_METERS
    fabric_conductance = EXTERIOR_WALL_U_VALUE_W_PER_M2_K * exterior_wall_area
    ventilation_conductance = (
        AIR_DENSITY_KG_PER_M3
        * AIR_HEAT_CAPACITY_J_PER_KG_K
        * volume_m3
        * VENTILATION_AIR_CHANGES_PER_HOUR
        / 3600
    )
    air_mass_conductance = floor_area_m2 * AIR_MASS_COUPLING_W_PER_M2_K
    total_outside_conductance = fabric_conductance + ventilation_conductance

    # Substeps keep this explicit two-node heat balance stable at larger API timesteps.
    substep_count = max(1, int(duration_seconds // 60) + 1)
    substep_seconds = duration_seconds / substep_count
    for _ in range(substep_count):
        outside_loss = total_outside_conductance * (
            air_temperature - outside_temperature
        )
        mass_exchange = air_mass_conductance * (mass_temperature - air_temperature)
        #required_heating = (
        #    (setpoint - air_temperature) * air_capacity / substep_seconds
        #    - mass_exchange
        #    - internal_gains_watts
        #    + outside_loss
        #)
        #heater_watts = (
        #    min(heater_max_watts, max(0.0, required_heating))
        #    if air_temperature < setpoint
        #    else 0.0
        #)
        heater_watts = heater_max_watts
        air_temperature += (
            heater_watts
            + internal_gains_watts
            - outside_loss
            + mass_exchange
        ) * substep_seconds / air_capacity
        mass_temperature -= (
            mass_exchange * substep_seconds / mass_capacity
        )

    return air_temperature, mass_temperature




# 1. Defeniera vad som ska hända när klienten ansluter till brokern
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("Ansluten till brokern!")
        # Prenumerera på önskat ämne efter lyckad anslutning
        # Ersätt "test/topic" med ditt eget ämne. Använd "#" som wildcard för alla ämnen.
        client.subscribe(userdata["listen_topic"])
    else:
        print(f"Anslutning misslyckades med kod: {reason_code}")

# 2. Defeniera vad som ska hända när ett nytt meddelande tas emot
def on_message(client, userdata, msg):
    # msg.payload kommer som bytes, använd .decode() för att göra om till text (str)
    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    #dic_response = json.loads(msg.payload.decode('utf-8'))
    
    dic_response = json.loads(msg.payload.decode('utf-8').replace("'",'"'))

    print(dic_response)
    
    try 
        response = requests.get(str(BASE_OCC+"api/state"), headers=headers)
        dic_response = json.loads(requests.text)
        outside_temperature= 
    except:
        print("Couldn't get clock")
        outside_temperature=0
    print(dic_response)
    room = userdata["room"]
    if "watt" in dic_response:
        
        room["air_temperature"], room["mass_temperature"] = simulate_step(
                    air_temperature=room["air_temperature"],
                    mass_temperature=room["mass_temperature"],
                    volume_m3=room["area"] * ROOM_HEIGHT_METERS,
                    floor_area_m2=room["area"],
                    exterior_wall_length_m=room["wall_length"],
                    outside_temperature=outside_temperature,
                    heater_max_watts=dic_response["watt"],
                    duration_seconds=timestep.total_seconds(),
                    internal_gains_watts=0,
                )
        
        payload={
            "state":dic_response["watt"],
            }
        response = requests.put(str(BASE+f"api/actuators/{userdata["room"]}-watt/state"), json=payload, headers=headers)
        dic_response = json.loads(response.text)
        print(dic_response)


# 4. Ange broker-adress och port
# "localhost" för en lokal Mosquitto, eller extern IP/domän
BROKER = "localhost" 
PORT = 1883


    
def main():
    args = parse_args()
    
    room = {
        "name": args.room,
        "level": args.level
    }
    lecture_data = load_json(DATA_DIR / "Lectures.json")
    weather_data = load_json(DATA_DIR / "Weather.json")
    room_data = load_json(DATA_DIR / "rooms.json")
    for i in room_data:
        if i["name"]==room["name"] and i["level"] == room["level"]:
            room["wall_length"] = float(i["walls"])
            break
    schedule = lecture_data["schedule"]
    sessions = lecture_data["sessions"]
    weather_by_day = prepare_weather(weather_data["weather"])
    floor_data=requests.get(BASE+ f"api/building/floors/level{room["level"]}")
    for i in floor_data:
        if i["name"]==room["name"] and i["level"] == room["level"]:
            room["wall_length"] = float(i["walls"])
    
    if "area" not in room:
        raise AttributeError("Room or level incorrect")
    print("Ansluter till MQTT-broker...")
    
    room["air_temperature"] = args.temperature#requests.get(str(BASE+f"api/sensors/{sensor["id"]}"), json=sensor, headers=headers)
    room["mass_temperature"] = args.temperature
    
    # 3. Initiera klienten (Viktigt: Ange CallbackAPIVersion.VERSION2 för paho-mqtt v2.x)
    userdata = {
        "listen_topic": f"{args.level}/{args.room}/{args.type}/sim",
        "send_topic": f"{args.level}/{args.room}/{args.type}/sensor",
        "room": room
    }
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        userdata=userdata  # <--- HÄR skickar du med datan
    )
    
    # Koppla dina funktioner till klientens callbacks
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, keepalive=60)
    
    # 5. Starta nätverksloopen som lyssnar efter meddelanden i bakgrunden
    # loop_forever() blockerar programmet och körs tills du stänger av med Ctrl+C
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nAvslutar...")
        client.disconnect()
    
if __name__ == "__main__":
    main()