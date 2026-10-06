# EN(1) equipment
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

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}

def parse_args():
    parser = argparse.ArgumentParser(description="One equipment")
    parser.add_argument("--id", default="hvac-A109")
    parser.add_argument("--name", default="HVAC A109")
    parser.add_argument("--type", default="ac_unit")
    parser.add_argument("--category", default="hvac")
    parser.add_argument("--level", default="level0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--status", default="running")
    parser.add_argument("--sensor", default="")
    parser.add_argument("--actuator", default="")
    
    return parser.parse_args()


def main():
    args = parse_args()
    response = requests.post(str(BASE+"api/equipment"), json=vars(args), headers=headers)
    dic_response = json.loads(response.text)
    print(dic_response)
    
    
    
    
    
if __name__ == "__main__":
    main()