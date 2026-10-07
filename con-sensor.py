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

def parse_args():
    parser = argparse.ArgumentParser(description="One equipment")
    parser.add_argument("--id", default="temp-A109")
    parser.add_argument("--name", default="Temperature Sensor A109")
    parser.add_argument("--type", default="temperature_sensor")
    parser.add_argument("--category", default="monitoring")
    parser.add_argument("--level", default="level0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--status", default="running")
    parser.add_argument("--sensor", default='{"id":"A109-temp", "name":"Temperature", "type":"temperature", "data_type":"text", "unit":"°C", "value":25 }')
    return parser.parse_args()


def main():
    args = parse_args()
    response = requests.post(str(BASE+"api/equipment"), json=vars(args), headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    #Websocket wait for update
    publish.single(
        topic="test/A109-temp-dec", 
        payload="Hej från Python!", 
        hostname="broker.hivemq.com" # Du kan byta ut denna mot din egen broker-IP/host
    )
    
    
    
    
    
if __name__ == "__main__":
    main()
    
    
