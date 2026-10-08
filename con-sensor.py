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
    dic_response = json.loads(response.text.replace("'",'"'))
    print(dic_response)
    publish.single(
        topic=f"{args.level}/{args.room}/{args.type}/dec", 
        payload=str(dic_response), 
        hostname="localhost" # Du kan byta ut denna mot din egen broker-IP/host
    )
    #Websocket wait for update
    
    
    
    
    
if __name__ == "__main__":
    main()
    
    
