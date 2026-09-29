import requests
import json
import sys
import sqlite3

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


#for i in range(len(levels)):
    