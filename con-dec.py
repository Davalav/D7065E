import argparse
import json
import logging
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
    parser.add_argument("--setpoint", type=float, default=DEFAULT_SET_TEMP)
    parser.add_argument("--kp", type=float, default=100.0, help="PID proportional gain (W/°C)")
    parser.add_argument("--ki", type=float, default=0.02, help="PID integral gain (W/(°C·s))")
    parser.add_argument("--kd", type=float, default=25.0, help="PID derivative gain (W·s/°C)")
    parser.add_argument("--max-watts", type=float, default=600.0)
    return parser.parse_args()


class PIDRegulator:
    def __init__(self, setpoint, kp, ki, kd, max_output):
        if max_output <= 0:
            raise ValueError("Maximum wattage must be positive")
        if min(kp, ki, kd) < 0:
            raise ValueError("PID gains must be non-negative")
        self.setpoint = setpoint
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.max_output = max_output
        self.integral = 0.0
        self.last_time = None
        self.last_measurement = None

    def update(self, measurement, now=None):
        now = time.monotonic() if now is None else now
        error = self.setpoint - measurement
        if self.last_time is None:
            self.last_time = now
            self.last_measurement = measurement
            return min(self.max_output, max(0.0, self.kp * error))

        elapsed = max(now - self.last_time, 1e-6)
        derivative = -(measurement - self.last_measurement) / elapsed
        candidate_integral = self.integral + error * elapsed
        proportional = self.kp * error
        derivative_term = self.kd * derivative
        candidate_output = (
            proportional + self.ki * candidate_integral + derivative_term
        )

        if (
            0.0 <= candidate_output <= self.max_output
            or (candidate_output > self.max_output and error < 0)
            or (candidate_output < 0 and error > 0)
        ):
            self.integral = candidate_integral

        output = proportional + self.ki * self.integral + derivative_term
        self.last_time = now
        self.last_measurement = measurement
        return min(self.max_output, max(0.0, output))


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("Ansluten till brokern!")
        client.subscribe(userdata["listen_topic"])
        client.publish(
            userdata["send_topic"],
            json.dumps({"set_temp": str(userdata["regulator"].setpoint)}),
        )
    else:
        print(f"Anslutning misslyckades med kod: {reason_code}")


def on_message(client, userdata, msg):
    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    try:
        reading = json.loads(msg.payload.decode("utf-8"))
        measured_temperature = float(reading["value"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        logging.exception("Ignoring invalid temperature reading")
        return

    wattage = userdata["regulator"].update(measured_temperature)
    client.publish(
        userdata["send_topic"],
        json.dumps({"watt": str(round(wattage, 2))}),
    )
    print(f"PID: {measured_temperature:.2f} °C -> {wattage:.2f} W")


def main():
    args = parse_args()
    if args.max_watts <= 0 or min(args.kp, args.ki, args.kd) < 0:
        raise ValueError("Maximum wattage must be positive and PID gains non-negative")
    print("Ansluter till MQTT-broker...")

    regulator = PIDRegulator(
        setpoint=args.setpoint,
        kp=args.kp,
        ki=args.ki,
        kd=args.kd,
        max_output=args.max_watts,
    )
    userdata = {
        "listen_topic": f"{args.level}/{args.room}/{args.type}/dec",
        "send_topic": f"{args.level}/{args.room}/{args.type}/ac",
        "regulator": regulator,
    }

    client = mqtt.Client(
        client_id=f"dec-{os.getpid()}-{args.level}-{args.room}",
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
