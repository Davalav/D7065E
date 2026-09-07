import requests
import json

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}


# Skapa en hvac med sensor och actuator i a109
payload = {"id":"hvac-A109","name":"HVAC A109","type":"ac_unit","category":"hvac","level":"level0","room":"A109","status":"running"}
response = requests.post(str(BASE+"api/equipment"), json=payload, headers=headers)
print(response.json())

payload = {"id":"A109-temp","name":"Temperature","type":"temperature","data_type":"text","unit":"°C","value":"18.0"}
response = requests.post(str(BASE+"api/equipment/hvac-A109/sensors"), json=payload, headers=headers)
print(response.json())

payload = {"id":"A109-set","name":"Setpoint","type":"setpoint","state":"21"}
response = requests.post(str(BASE+"api/equipment/hvac-A109/actuators"), json=payload, headers=headers)
print(response.json())

response = requests.get(str(BASE+'api/equipment/hvac-A109'))
object = json.loads(response.text)
print(object)

payload = {"data_type": "text", "value": str(round(18,2))}
response = requests.put(str(BASE+"api/sensors/A109-temp/value"), json=payload, headers=headers)
print(response.json())