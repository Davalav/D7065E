# Decision making
import time
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="One Decision maker")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--type", default="temp")
    #parser.add_argument("--sensor", default="")
    #parser.add_argument("--actuator", default="")
    return parser.parse_args()


# 1. Defeniera vad som ska hända när klienten ansluter till brokern
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("Ansluten till brokern!")
        # Prenumerera på önskat ämne efter lyckad anslutning
        # Ersätt "test/topic" med ditt eget ämne. Använd "#" som wildcard för alla ämnen.
        client.subscribe(f"test/{id}")
    else:
        print(f"Anslutning misslyckades med kod: {reason_code}")

# 2. Defeniera vad som ska hända när ett nytt meddelande tas emot
def on_message(client, userdata, msg):
    # msg.payload kommer som bytes, använd .decode() för att göra om till text (str)
    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")

# 3. Initiera klienten (Viktigt: Ange CallbackAPIVersion.VERSION2 för paho-mqtt v2.x)
client = mqtt.Client(CallbackAPIVersion.VERSION2)

# Koppla dina funktioner till klientens callbacks
client.on_connect = on_connect
client.on_message = on_message

# 4. Ange broker-adress och port
# "localhost" för en lokal Mosquitto, eller extern IP/domän
BROKER = "localhost" 
PORT = 1883

print("Ansluter till MQTT-broker...")
client.connect(BROKER, PORT, keepalive=60)

id = "A109-temp-dec"
# 5. Starta nätverksloopen som lyssnar efter meddelanden i bakgrunden
# loop_forever() blockerar programmet och körs tills du stänger av med Ctrl+C
try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\nAvslutar...")
    client.disconnect()
