import requests
import json
from time import sleep

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}

def step(BASE, setTemp,volume,deltaT,watt):
    response = requests.get(f'{BASE}api/actuators/A109-set')
    object = json.loads(response.text)
    temp = float(object["state"])
    print(temp)
    
    # Ekvation för värmetillförsel:
    # Q=\frac{m\cdot c\cdot \Delta T}{t}
    # Omskrivet
    # \Delta T=\frac{Q\cdot t}{m\cdot c}
    cp = 1000
    m = volume*1.225
    if(temp < setTemp):
        temp += (watt*deltaT)/(m*cp)
    #temp += 0.2*(setTemp-temp)
    payload = {"data_type": "text", "value": str(round(temp,2))}
    response = requests.put(str(BASE+"api/sensors/A109-temp/value"), json=payload, headers=headers)
    print(response.json())

response = requests.get(f'{BASE}api/building/floors/level0')
object = json.loads(response.text)
rooms = object["rooms"]
a109_area = rooms[97]['area']
print(rooms[97])

for i in range(5):
    response = requests.get(f'{BASE}api/sensors/A109-temp')
    object = json.loads(response.text)
    print(object["value"])
    temp = float(object["value"])
    step(BASE, temp, a109_area*3,5,100)
    sleep(5)