import requests
import json
from time import sleep
import sys
BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}
T_outside = 0
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

def step(BASE, curTemp,volume,deltaT,watt, room, walls):
    origWatt=watt
    response = requests.get(f'{BASE}api/actuators/{room}-set')
    object = json.loads(response.text)
    setTemp = float(object["state"])
    #print(setTemp)

    # Värmeförlust: https://home-energy-model.co.uk/technical/fabric-heat-loss/
    # Q=U\cdot A\cdot (T_inside-T_outside)
    U=0.25
    A= walls*3
    T_diff= curTemp-T_outside
    wattLoss= U*A*T_diff
    # Ekvation för värmetillförsel:
    # Q=\frac{m\cdot c\cdot \Delta T}{t}
    # Omskrivet
    # \Delta T=\frac{Q\cdot t}{m\cdot c}
    cp = 1000
    m = volume*1.225

    #Time to equilibrium (Inte helt korrekt då värmeförlusten är logaritmisk)

    curTemp -= (wattLoss*deltaT)/(m*cp)
    if(curTemp < setTemp):

        watt = min(watt,(m*cp*abs(setTemp-curTemp))/deltaT)
        #watt=0
        curTemp += (watt*deltaT)/(m*cp)
            
        if(origWatt == watt):
            t=(m*cp*(setTemp-curTemp))/(watt-wattLoss)
            print(f"time to equil: {format_seconds(t)}")
    #if(walls>0):
    #    curTemp=0
    #temp += 0.2*(setTemp-temp)
    #curTemp=volume/3
    payload = {"data_type": "text", "value": str(round(curTemp,2))}
    response = requests.put(str(BASE+f"api/sensors/{room}-temp/value"), json=payload, headers=headers)
    #print(response.json())
    #print(curTemp)
    return curTemp

if len(sys.argv) > 1 and sys.argv[1] == "Alfa":
    f = open("rooms.json")
    roomsJson = json.loads(f.read())
    #print(roomsJson)
    levels =[]
    rooms =[]
    walls =[]
    for i in roomsJson["rooms"]:
        levels.append(i["floor"])
        rooms.append(i["name"])
        walls.append(i["walls"])
else:
    levels = [sys.argv[1] if len(sys.argv) >1 else "0"]
    rooms = [sys.argv[2] if len(sys.argv) >2 else "A109"]
    f = open("rooms.json")
    roomsJson = json.loads(f.read())
    walls = []
    for i in roomsJson["rooms"]:
        print(i)
        if i["name"]=="A109":
            walls = [i["walls"]]
            print(f"Found A109: {walls}㎡")
            break

print("Json loaded")
areas = []
temps = []
for i in range(len(levels)):
    level = levels[i]
    room = rooms[i]
    # Get Area
    response = requests.get(f'{BASE}api/building/floors/level{level}')
    object = json.loads(response.text)
    ObjRooms = object["rooms"]
    #print(ObjRooms[0])
    for rum in ObjRooms:
        if rum["name"]== room:
            areas.append(rum["area"])
            #print("Found")
            break
            
    #room_area = next((rum for rum in ObjRooms if rum["name"]== room),None)['area']
    #areas.append(room_area)
    #a109_area = rooms[97]['area']
    #print(rooms[97])
    
    # Get temperature
    response = requests.get(f'{BASE}api/sensors/{room}-temp')
    object = json.loads(response.text)
    #print(object["value"])
    try:
        temp = float(object["value"])
        temps.append(temp)
    except:
        print(object)
        print(room)
    # Set Hvac running
    response = requests.get(str(BASE+f'api/equipment/hvac-{room}'))
    payload = json.loads(response.text)
    payload["status"] = "running"
    response = requests.put(str(BASE+f"api/equipment/hvac-{room}"), json=payload, headers=headers)
    #print(response.json())

print("Area loaded. Hvac activated")
time = 9*60*60 #Time in seconds
timestep = 60 #Time in seconds
print("starting sim")
for t in range(100):
    for i in range(len(levels)):
        temps[i] = step(BASE, temps[i], areas[i]*3,timestep,500, rooms[i], walls[i])
    time+= timestep
    print(f"Timestep: {format_seconds(time)}")
    sleep(1)
        
for i in range(len(levels)):
    # Set Hvac stopped    
    payload["sensors"][0]["value"]=str(round(temps[i],2))
    payload["status"] = "stopped"
    response = requests.put(str(BASE+f"api/equipment/hvac-{rooms[i]}"), json=payload, headers=headers)
print(response.json())