# EN(1) sensor
import requests
import json
import sys
import time
import argparse
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
from time import sleep
import paho.mqtt.publish as publish
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}
default_temp=25
default_co2=400
default_occ=0


equipments = {
    "co2":({
        "id": "co2-",
        "name": "CO2 Sensor ",
        "type": "co2_sensor",
        "category": "monitoring",
    },
    {
            "id":"-co2",
            "name":"CO2",
            "type":"co2",
            "data_type":"text",
            "unit":"ppm",
            "value":str(default_co2)
    }),
    "temp":({
        "id": "temp-",
        "name": "Temperature Sensor ",
        "type": "temperature_sensor",
        "category": "monitoring",
        
    },
    {
        "id":"-temp",
        "name":"Temperature",
        "type":"temperature",
        "data_type":"text",
        "unit":"°C",
        "value":str(default_temp)
    })
}

def parse_args():
    parser = argparse.ArgumentParser(description="One equipment")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--type", default="temp")
    return parser.parse_args()



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
    sensor = userdata["sensor"]
    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    reading = json.loads(msg.payload.decode("utf-8"))
    sensor["value"] = str(reading["value"])
    
    json = {
        "data_type": sensor["data_type"],
        "value": reading["value"]
    }
    response = requests.put(
        f"{BASE}api/sensors/{sensor['id']}",
        json=json,
        headers=headers,
    )
    response.raise_for_status()
    sensor_response = response.json()
    
    publish.single(
        topic=userdata["send_topic"], 
        payload=json.dumps(sensor_response),
        hostname="localhost" # Du kan byta ut denna mot din egen broker-IP/host
    )
    print(f"Updated sensor {sensor['id']} to {sensor['value']}")


# 4. Ange broker-adress och port
# "localhost" för en lokal Mosquitto, eller extern IP/domän
BROKER = "localhost" 
PORT = 1883

def main():
    args = parse_args()
    equip = equipments[args.type][0]
    equip["id"] = equip["id"] + args.room
    equip["name"] = equip["name"]+ args.room
    equip["level"] = "level"+args.level
    equip["room"] = args.room
    equip["status"] = "running"
    response = requests.post(str(BASE+"api/equipment"), json=equip, headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    sensor = equipments[args.type][1]
    sensor["id"] = args.room + sensor["id"]
    response = requests.post(str(BASE+f"api/equipment/{args.type}-{args.room}/sensors"), json=sensor, headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    
    response = requests.get(str(BASE+f"api/sensors/{sensor["id"]}"), json=sensor, headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    publish.single(
        topic=f"{args.level}/{args.room}/{args.type}/dec", 
        payload=str(dic_response), 
        hostname="localhost" # Du kan byta ut denna mot din egen broker-IP/host
    )
    
    userdata = {
        "send_topic": f"{args.level}/{args.room}/{args.type}/dec",
        "listen_topic": f"{args.level}/{args.room}/{args.type}/sensor",
        "sensor": sensor,
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
    
    
