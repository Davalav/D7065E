# En Actuator
import time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import argparse
import paho.mqtt.publish as publish
import json
import requests


BASE="http://127.0.0.1:9090/"

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

def parse_args():
    parser = argparse.ArgumentParser(description="One HVAC")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--type", default="temp")
    #parser.add_argument("--sensor", default="")
    #parser.add_argument("--actuator", default="")
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
    # msg.payload kommer som bytes, använd .decode() för att göra om till text (str)
    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    #dic_response = json.loads(msg.payload.decode('utf-8'))
    
    dic_response = json.loads(msg.payload.decode('utf-8').replace("'",'"'))

    print(dic_response)
    
    if "watt" in dic_response:
        payload={
            "state":dic_response["watt"],
            }
        response = requests.put(str(BASE+f"api/actuators/{userdata["room"]}-watt/state"), json=payload, headers=headers)
        dic_response = json.loads(response.text)
        print(dic_response)
    if "set_temp" in dic_response:
        payload={
            "state":dic_response["set_temp"],
            }
        response = requests.put(str(BASE+f"api/actuators/{userdata["room"]}-set/state"), json=payload, headers=headers)
        dic_response = json.loads(response.text)
        print(dic_response)


# 4. Ange broker-adress och port
# "localhost" för en lokal Mosquitto, eller extern IP/domän
BROKER = "localhost" 
PORT = 1883


    
def main():
    args = parse_args()
    
    hvac = equipments["hvac"]
    hvac["id"] = hvac["id"] + args.room
    hvac["name"] = hvac["name"]+ args.room
    hvac["level"] = "level"+args.level
    hvac["room"] = args.room
    hvac["status"] = "running"
    response = requests.post(str(BASE+"api/equipment"), json=hvac, headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    
    set_temp = equipments["set_temp"]
    set_temp["id"] = args.room + set_temp["id"]
    response = requests.post(str(BASE+f"api/equipment/hvac-{args.room}/actuators"), json=set_temp, headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    watt = equipments["watt"]
    watt["id"] = args.room + watt["id"]
    response = requests.post(str(BASE+f"api/equipment/hvac-{args.room}/actuators"), json=watt, headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    print("Ansluter till MQTT-broker...")
    
    # 3. Initiera klienten (Viktigt: Ange CallbackAPIVersion.VERSION2 för paho-mqtt v2.x)
    userdata = {
        "listen_topic": f"{args.level}/{args.room}/{args.type}/ac",
        "send_topic": f"{args.level}/{args.room}/{args.type}/sim",
        "room": args.room
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