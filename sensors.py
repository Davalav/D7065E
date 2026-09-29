import requests
import json
import sys
import sqlite3

# sqlit för att öppna databasen
# exempel:
# sqlit connect sqlite --file-path "data.db"

BASE="http://127.0.0.1:9090/"

headers = {'Content-Type': 'application/json'}

if len(sys.argv) > 1 and sys.argv[1] == "Alfa":
    f = open("rooms.json")
    roomsJson = json.loads(f.read())
    #print(roomsJson)
    levels =[]
    rooms =[]
    for i in roomsJson["rooms"]:
        levels.append(i["floor"])
        rooms.append(i["name"])
else:
    levels = [sys.argv[1] if len(sys.argv) >1 else "0"]
    rooms = [sys.argv[2] if len(sys.argv) >2 else "A109"]
    
conn = sqlite3.connect('data.db')
c = conn.cursor() # cursor
# SQL query to create the table
table_creation_query = """
    CREATE TABLE IF NOT EXISTS Rooms (
        Name VARCHAR(20) NOT NULL,
        Floor INT NOT NULL,
        Temperature FLOAT,
        CO2 FLOAT,
        PRIMARY KEY (Name, Floor)
    );
"""
c.execute(table_creation_query)

query = 'SELECT sqlite_version();'
c.execute(query)

room_creation_query = """
INSERT INTO Rooms(Name, Floor, Temperature, CO2)
Values(?, ?, ?, ?);
"""
#ON CONFLICT (Name, Floor);

for i in range(len(levels)):
    level = levels[i]
    room = rooms[i]
    response = requests.get(str(BASE+f'api/sensors/{room}-temp'))
    dic_response = json.loads(response.text)
    temp = dic_response["value"]
    #print(dic_response)
    
    response = requests.get(str(BASE+f'api/sensors/{room}-co2'))
    dic_response = json.loads(response.text)
    co2=dic_response["value"]
    #print(dic_response)
    
    #print(room_creation_query)
    try:
        c.execute(room_creation_query, (room, level, temp, co2))
    except Exception as e:
        print(e)
        print(f"{room} {level} {temp} {co2}")
    conn.commit()
c.close()


    