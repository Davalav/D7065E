import requests
import json
import sys

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}

level = sys.argv[1] if len(sys.argv) >1 else "0"
room = sys.argv[2] if len(sys.argv) >2 else "A109"



# Skapa en hvac med sensor och actuator i a109
payload = {"id":f"hvac-{room}","name":f"HVAC {room}","type":"ac_unit","category":"hvac","level":f"level{level}","room":room,"status":"stopped"}
response = requests.post(str(BASE+"api/equipment"), json=payload, headers=headers)
print(response.json())

payload = {"id":f"{room}-temp","name":"Temperature","type":"temperature","data_type":"text","unit":"°C","value":"18.0"}
response = requests.post(str(BASE+f"api/equipment/hvac-{room}/sensors"), json=payload, headers=headers)
print(response.json())

payload = {"id":f"{room}-set","name":"Setpoint","type":"setpoint","state":"21"}
response = requests.post(str(BASE+f"api/equipment/hvac-{room}/actuators"), json=payload, headers=headers)
print(response.json())

response = requests.get(str(BASE+f'api/equipment/hvac-{room}'))
object = json.loads(response.text)
print(object)

payload = {"data_type": "text", "value": str(round(10,2))}
response = requests.put(str(BASE+f"api/sensors/{room}-temp/value"), json=payload, headers=headers)
print(response.json())