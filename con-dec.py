import argparse
import json
import logging
import os
import time
from datetime import datetime

import paho.mqtt.client as mqtt
import requests
from paho.mqtt.client import CallbackAPIVersion

from control_safety import ActuatorAckMonitor, SensorHealthMonitor


CONNECT_RETRY_SECONDS = 2
HEALTH_CHECK_INTERVAL_SECONDS = 1
BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = 1883
OCCUPANCY_URL = os.getenv("OCCUPANCY_URL", "http://127.0.0.1:8081").rstrip("/")
DEFAULT_SET_TEMP = 21
DEFAULT_NIGHT_SET_TEMP = 17


def parse_args():
    parser = argparse.ArgumentParser(description="One Decision maker")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--type", default="temp")
    parser.add_argument("--setpoint", type=float, default=DEFAULT_SET_TEMP)
    parser.add_argument("--kp", type=float, default=100.0, help="PID proportional gain (W/°C)")
    parser.add_argument("--ki", type=float, default=0.02, help="PID integral gain (W/(°C·s))")
    parser.add_argument("--kd", type=float, default=25.0, help="PID derivative gain (W·s/°C)")
    parser.add_argument("--max-watts", type=float, default=30000.0)
    return parser.parse_args()


class PIDRegulator:
    def __init__(self, setpoint, kp, ki, kd, max_output, reverse_action=False):
        if max_output <= 0:
            raise ValueError("Maximum wattage must be positive")
        if min(kp, ki, kd) < 0:
            raise ValueError("PID gains must be non-negative")
        self.setpoint = setpoint
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.max_output = max_output
        self.error_direction = 1.0 if reverse_action else -1.0
        self.integral = 0.0
        self.last_time = None
        self.last_measurement = None

    def update(self, measurement, now=None):
        now = time.monotonic() if now is None else now
        error = (measurement - self.setpoint) * self.error_direction
        if self.last_time is None:
            self.last_time = now
            self.last_measurement = measurement
            return min(self.max_output, max(0.0, self.kp * error))

        elapsed = max(now - self.last_time, 1e-6)
        derivative = (
            (measurement - self.last_measurement)
            * self.error_direction
            / elapsed
        )
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


def current_setpoint():
    response = requests.get(f"{OCCUPANCY_URL}/api/state", timeout=5)
    response.raise_for_status()
    clock_time = datetime.fromisoformat(
        response.json()["sim"]["clock"]["time"]
    ).hour
    if clock_time >= 18 or clock_time < 6:
        return DEFAULT_NIGHT_SET_TEMP
    return DEFAULT_SET_TEMP


def configured_setpoint(userdata):
    if userdata["sensor_type"] == "temp":
        return current_setpoint()
    return userdata["configured_setpoint"]


def update_setpoint(client, userdata, force=False):
    setpoint = configured_setpoint(userdata)
    regulator = userdata["regulator"]
    if force or regulator.setpoint != setpoint:
        regulator.setpoint = setpoint
        if userdata["sensor_type"] == "temp":
            client.publish(
                userdata["send_topic"],
                json.dumps({"set_temp": str(setpoint)}),
            )
        logging.info("Setpoint changed to %s for %s", setpoint, userdata["sensor_type"])


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("Ansluten till brokern!")
        client.subscribe(userdata["listen_topic"])
        client.subscribe(userdata["ack_topic"])
        try:
            update_setpoint(client, userdata, force=True)
        except (requests.RequestException, KeyError, TypeError, ValueError):
            logging.exception("Could not read occupancy simulator time for setpoint")
    else:
        print(f"Anslutning misslyckades med kod: {reason_code}")


def on_message(client, userdata, msg):
    if msg.topic == userdata["ack_topic"]:
        try:
            acknowledgement = json.loads(msg.payload.decode("utf-8"))
            accepted = userdata["actuator_monitor"].acknowledge(
                acknowledgement["command_id"], acknowledgement["state"]
            )
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            logging.exception("Ignoring invalid actuator acknowledgement")
            return
        if not accepted:
            logging.error("Actuator failed to apply the latest command")
        else:
            logging.info("Actuator command %s confirmed", acknowledgement["command_id"])
        return

    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    try:
        reading = json.loads(msg.payload.decode("utf-8"))
        measured_value = float(reading["value"])
        userdata["sensor_monitor"].observe(
            measured_value, time.monotonic()
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        logging.exception("Ignoring invalid %s reading", userdata["sensor_type"])
        return

    failure_reason = userdata["sensor_monitor"].failure_reason(time.monotonic())
    if failure_reason:
        if not userdata["fail_safe"]:
            logging.error(
                "%s %s; entering fail-safe mode",
                userdata["sensor_type"],
                failure_reason,
            )
            publish_wattage(client, userdata, safe_output(userdata))
            userdata["fail_safe"] = True
        return
    if userdata["fail_safe"]:
        logging.info("%s sensor recovered; resuming PID control", userdata["sensor_type"])
        userdata["fail_safe"] = False

    try:
        update_setpoint(client, userdata)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        logging.exception("Ignoring reading because setpoint is unavailable")
        return

    wattage = userdata["regulator"].update(measured_value)
    publish_wattage(client, userdata, wattage)
    print(f"PID: {measured_value:.2f} -> {wattage:.2f} W")


def safe_output(userdata):
    if userdata["sensor_type"] == "co2":
        return userdata["regulator"].max_output
    return 0.0


def publish_wattage(client, userdata, wattage):
    command_id = userdata["next_command_id"]
    userdata["next_command_id"] += 1
    payload = {
        "watt": str(round(wattage, 2)),
        "command_id": command_id,
    }
    userdata["last_command_payload"] = payload
    userdata["actuator_monitor"].command_sent(
        command_id, payload["watt"], time.monotonic()
    )
    client.publish(userdata["send_topic"], json.dumps(payload))


def health_watchdog(client, userdata):
    now = time.monotonic()
    reason = userdata["sensor_monitor"].failure_reason(now)
    if reason and not userdata["fail_safe"]:
        logging.error("%s %s; entering fail-safe mode", userdata["sensor_type"], reason)
        publish_wattage(client, userdata, safe_output(userdata))
        userdata["fail_safe"] = True

    monitor = userdata["actuator_monitor"]
    if monitor.timed_out(now):
        logging.error(
            "%s actuator did not confirm command %s; retrying command",
            userdata["sensor_type"],
            monitor.command_id,
        )
        client.publish(
            userdata["send_topic"],
            json.dumps(userdata["last_command_payload"]),
        )
        monitor.mark_retry(now)


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
        reverse_action=args.type == "co2",
    )
    userdata = {
        "listen_topic": f"{args.level}/{args.room}/{args.type}/dec",
        "send_topic": f"{args.level}/{args.room}/{args.type}/ac",
        "ack_topic": f"{args.level}/{args.room}/{args.type}/actuator-status",
        "regulator": regulator,
        "sensor_type": args.type,
        "configured_setpoint": args.setpoint,
        "sensor_monitor": SensorHealthMonitor(
            stale_after=15.0,
            stuck_samples=5,
            started_at=time.monotonic(),
        ),
        "actuator_monitor": ActuatorAckMonitor(response_timeout=10.0),
        "next_command_id": 1,
        "last_command_payload": None,
        "fail_safe": False,
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
        client.loop_start()
        while True:
            health_watchdog(client, userdata)
            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nAvslutar...")
        client.loop_stop()
        client.disconnect()
    
if __name__ == "__main__":
    main()
