import requests
import json
from time import sleep

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}
T_outside = -40

def format_seconds(seconds: float) -> str:
    """
    Convert a float number of seconds into a human-readable string.
    Automatically scales from milliseconds up to days.
    """
    abs_seconds = abs(seconds)
    sign = "-" if seconds < 0 else ""

    if abs_seconds < 1e-3:
        return f"{sign}{abs_seconds * 1e6:.3f} µs"
    elif abs_seconds < 1:
        return f"{sign}{abs_seconds * 1e3:.3f} ms"
    elif abs_seconds < 60:
        return f"{sign}{abs_seconds:.3f} s"
    elif abs_seconds < 3600:
        return f"{sign}{abs_seconds / 60:.3f} min"
    #elif abs_seconds < 86400:
    else:
        return f"{sign}{abs_seconds / 3600:.3f} h"
    #else:
    #    return f"{sign}{abs_seconds / 86400:.3f} days"

def step(BASE, curTemp,volume,deltaT,watt):
    response = requests.get(f'{BASE}api/actuators/A109-set')
    object = json.loads(response.text)
    setTemp = float(object["state"])
    #print(setTemp)
    
    # Värmeförlust: https://home-energy-model.co.uk/technical/fabric-heat-loss/
    # Q=U\cdot A\cdot (T_inside-T_outside)
    U=0.25
    A= 20
    T_diff= curTemp-T_outside
    wattLoss= U*A*T_diff
    # Ekvation för värmetillförsel:
    # Q=\frac{m\cdot c\cdot \Delta T}{t}
    # Omskrivet
    # \Delta T=\frac{Q\cdot t}{m\cdot c}
    cp = 1000
    m = volume*1.225
    
    #Time to equilibrium
    t=(m*cp*(setTemp-curTemp))/(watt-wattLoss)
    print(f"time to equil: {format_seconds(t)}")
    
    curTemp -= (wattLoss*deltaT)/(m*cp)
    if(curTemp < setTemp):
        
        watt = min(watt,(m*cp*abs(setTemp-curTemp))/deltaT)
        
        curTemp += (watt*deltaT)/(m*cp)
    #temp += 0.2*(setTemp-temp)
    payload = {"data_type": "text", "value": str(round(curTemp,2))}
    response = requests.put(str(BASE+"api/sensors/A109-temp/value"), json=payload, headers=headers)
    print(response.json())
    print(curTemp)
    return curTemp

# Get Area
response = requests.get(f'{BASE}api/building/floors/level0')
object = json.loads(response.text)
rooms = object["rooms"]
a109_area = rooms[97]['area']
print(rooms[97])

# Get temperature
response = requests.get(f'{BASE}api/sensors/A109-temp')
object = json.loads(response.text)
print(object["value"])
temp = float(object["value"])

# Set Hvac running
response = requests.get(str(BASE+f'api/equipment/hvac-A109'))
payload = json.loads(response.text)
payload["status"] = "running"
response = requests.put(str(BASE+"api/equipment/hvac-A109"), json=payload, headers=headers)
print(response.json())

for i in range(100):
    temp = step(BASE, temp, a109_area*3,60*60,500)
    sleep(5)

# Set Hvac stopped    
payload["sensors"][0]["value"]=str(round(temp,2))
payload["status"] = "stopped"
response = requests.put(str(BASE+"api/equipment/hvac-A109"), json=payload, headers=headers)
print(response.json())