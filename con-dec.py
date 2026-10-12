import argparse
import json
import os
import time

import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion


CONNECT_RETRY_SECONDS = 2
BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = 1883
DEFAULT_SET_TEMP = 21

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
        client.subscribe(userdata["listen_topic"])
        client.publish(
            userdata["send_topic"],
            json.dumps({"set_temp": str(DEFAULT_SET_TEMP)}),
        )
    else:
        print(f"Anslutning misslyckades med kod: {reason_code}")


def on_message(client, userdata, msg):
    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    client.publish(
        userdata["send_topic"],
        json.dumps({"watt": "300"}),
    )
    print("Uppdaterar watt")


def main():
    args = parse_args()
    print("Ansluter till MQTT-broker...")
    
    userdata = {
        "listen_topic": f"{args.level}/{args.room}/{args.type}/dec",
        "send_topic": f"{args.level}/{args.room}/{args.type}/ac"
    }

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        userdata=userdata,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        while True:
            try:
                client.connect(BROKER, PORT, keepalive=60)
                break
            except OSError as error:
                print(
                    f"Could not connect to MQTT broker at {BROKER}:{PORT}: {error}. "
                    f"Retrying in {CONNECT_RETRY_SECONDS}s."
                )
                time.sleep(CONNECT_RETRY_SECONDS)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nAvslutar...")
        client.disconnect()
    
if __name__ == "__main__":
    main()
