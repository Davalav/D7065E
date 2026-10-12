import argparse
import json
import logging
import os
import time
from urllib.parse import quote

import paho.mqtt.client as mqtt
import requests
from paho.mqtt.client import CallbackAPIVersion


BUILD_SIM_URL = os.getenv("BUILDSIM_URL", "http://127.0.0.1:9090").rstrip("/")
BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = 1883
CONNECT_RETRY_SECONDS = 2
REQUEST_TIMEOUT = 10


def parse_args():
    parser = argparse.ArgumentParser(description="One ventilation actuator")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--type", default="co2")
    return parser.parse_args()


def ensure_ventilator(session, level, room):
    equipment_id = f"vent-{room}"
    actuator_id = f"{room}-vent"
    equipment = {
        "id": equipment_id,
        "name": f"Ventilation {room}",
        "type": "ventilation_unit",
        "category": "ventilation",
        "level": f"level{level}",
        "room": room,
        "status": "running",
    }
    response = session.get(
        f"{BUILD_SIM_URL}/api/equipment", timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    existing = response.json()
    if not any(item.get("id") == equipment_id for item in existing):
        response = session.post(
            f"{BUILD_SIM_URL}/api/equipment",
            json=equipment,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        existing.append(equipment)

    equipment_data = next(item for item in existing if item.get("id") == equipment_id)
    if not any(
        actuator.get("id") == actuator_id
        for actuator in equipment_data.get("actuators") or []
    ):
        actuator = {
            "id": actuator_id,
            "name": "Ventilation power",
            "type": "ventilation",
            "state": "0",
            "unit": "W",
        }
        response = session.post(
            f"{BUILD_SIM_URL}/api/equipment/{quote(equipment_id, safe='')}/actuators",
            json=actuator,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logging.info("Connected to MQTT broker")
        client.subscribe(userdata["listen_topic"])
    else:
        logging.error("MQTT connection failed with code %s", reason_code)


def on_message(client, userdata, message):
    try:
        command = json.loads(message.payload.decode("utf-8"))
        wattage = float(command["watt"])
        if wattage < 0:
            raise ValueError("Ventilation wattage must be non-negative")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        logging.exception("Ignoring invalid ventilation command")
        return

    try:
        response = requests.put(
            f"{BUILD_SIM_URL}/api/actuators/{quote(userdata['actuator_id'], safe='')}/state",
            json={"state": str(wattage)},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        actual = requests.get(
            f"{BUILD_SIM_URL}/api/actuators/{quote(userdata['actuator_id'], safe='')}",
            timeout=REQUEST_TIMEOUT,
        )
        actual.raise_for_status()
        client.publish(
            userdata["ack_topic"],
            json.dumps({
                "command_id": command["command_id"],
                "state": actual.json()["state"],
            }),
        )
        logging.info("Updated %s to %.2f W", userdata["actuator_id"], wattage)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        logging.exception("Failed to apply ventilation command; controller will retry")


def main():
    args = parse_args()
    session = requests.Session()
    ensure_ventilator(session, args.level, args.room)

    userdata = {
        "listen_topic": f"{args.level}/{quote(args.room, safe='')}/{args.type}/ac",
        "ack_topic": f"{args.level}/{quote(args.room, safe='')}/{args.type}/actuator-status",
        "actuator_id": f"{args.room}-vent",
    }
    client = mqtt.Client(
        client_id=f"vent-{os.getpid()}-{args.level}-{args.room}",
        callback_api_version=CallbackAPIVersion.VERSION2,
        userdata=userdata,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            client.connect(BROKER, PORT, keepalive=60)
            break
        except OSError as error:
            logging.warning(
                "Could not connect to MQTT broker at %s:%s: %s. Retrying in %ss.",
                BROKER,
                PORT,
                error,
                CONNECT_RETRY_SECONDS,
            )
            time.sleep(CONNECT_RETRY_SECONDS)

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Stopping ventilation actuator")
        client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
