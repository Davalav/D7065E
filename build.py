import requests
import json
import sys
import time

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}

if len(sys.argv) > 1 and sys.argv[1] == "Alfa":
    f = open("JSON files/rooms.json")
    roomsJson = json.loads(f.read())
    #print(roomsJson)
    levels =[]
    rooms =[]
    for i in roomsJson["rooms"]:
        levels.append(i["floor"])
        rooms.append(i["name"])
    print("loaded Alfa")
else:
    levels = [sys.argv[1] if len(sys.argv) >1 else "0"]
    rooms = [sys.argv[2] if len(sys.argv) >2 else "A109"]

set_temp= 21
cur_temp = 25
cur_co2=420
default_wattage=300
equipment= [
    {
        "id": "hvac-",
        "name": "HVAC ",
        "type": "ac_unit",
        "category": "hvac",      
    },
    {
        "id": "co2-",
        "name": "CO2 Sensor ",
        "type": "co2_sensor",
        "category": "monitoring",
    },
    {
        "id": "occupancy-",
        "name": "Occupancy Counter ",
        "type": "occupancy_counter",
        "category": "monitoring",
    },
    {
        "id": "temp-",
        "name": "Temperature Sensor ",
        "type": "temperature_sensor",
        "category": "monitoring",
    }
]

sensors = [
    (
        "temp",
        {
            "id":"-temp",
            "name":"Temperature",
            "type":"temperature",
            "data_type":"text",
            "unit":"°C",
            "value":str(cur_temp)
        }
    ),
    (
        "co2",
        {
            "id":"-co2",
            "name":"CO2",
            "type":"co2",
            "data_type":"text",
            "unit":"ppm",
            "value":str(cur_co2)
        }
    )
]
fails=0
for i in range(len(levels)):
    level = levels[i]
    room = rooms[i]
    # Skapa en hvac med sensor och actuator i a109
    for equip in equipment:
        equip = equip.copy()
        equip["id"] = equip["id"] + room
        equip["name"] = equip["name"]+ room
        equip["level"] = "level"+str(level)
        equip["room"] = room
        equip["status"] = "stopped"
        response = requests.post(str(BASE+"api/equipment"), json=equip, headers=headers)
        dic_response = json.loads(response.text)

        #if dic_response.contains("404"):
        #if type(dic_response) is not dict:
        if "error" in dic_response:
            print(equip)
            #print(response)
            print(dic_response)
            fails += 1
            #print(type(response))

    payload = {"id":f"{room}-set","name":"Setpoint","type":"setpoint","state":f"{set_temp}"}
    response = requests.post(str(BASE+f"api/equipment/hvac-{room}/actuators"), json=payload, headers=headers)
    payload = {"id":f"{room}-watt","name":"Wattage","type":"wattage","state":f"{default_wattage}"}
    response = requests.post(str(BASE+f"api/equipment/hvac-{room}/actuators"), json=payload, headers=headers)
    #payload = {"id":f"hvac-{room}","name":f"HVAC {room}","type":"ac_unit","category":"hvac","level":f"level{level}","room":room,"status":"stopped"}
    #response = requests.post(str(BASE+"api/equipment"), json=payload, headers=headers)
    #print(response.json())
    
    
    #payload = {"id":f"hvac-{room}","name":f"HVAC {room}","type":"ac_unit","category":"hvac","level":f"level{level}","room":room,"status":"stopped"}
    #response = requests.post(str(BASE+"api/equipment"), json=payload, headers=headers)
print(f"Added equipment and for {len(levels)} rooms with {fails} fails")
fails=0
time.sleep(1)

for i in range(len(levels)):
    level = levels[i]
    room = rooms[i]
    for sensor in sensors:
        payload = sensor[1].copy()
        payload["id"] = room+ payload["id"]
        response = requests.post(str(BASE+f"api/equipment/{sensor[0]}-{room}/sensors"), json=payload, headers=headers)
        dic_response = json.loads(response.text)

        #if type(dic_response) is not dict:
        #if dic_response.contains("404"):
        if "error" in dic_response:
            print(payload)
            print(dic_response)
            fails += 1
            #print(type(response))


    
    
    #payload = {"id":f"{room}-temp","name":"Temperature","type":"temperature","data_type":"text","unit":"°C","value":str(set_temp)}
    #response = requests.post(str(BASE+f"api/equipment/hvac-{room}/sensors"), json=payload, headers=headers)
    #print(response.json())

    #print(response.json())
    
    #response = requests.get(str(BASE+f'api/equipment/hvac-{room}'))
    #object = json.loads(response.text)
    #print(object)
    
    #payload = {"data_type": "text", "value": str(round(cur_temp,2))}
    #response = requests.put(str(BASE+f"api/sensors/{room}-temp/value"), json=payload, headers=headers)
print(f"Added sensors for {len(levels)} rooms with {fails} fails")

#print(response.json())