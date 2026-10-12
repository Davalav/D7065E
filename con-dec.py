# Decision maker for every simulated room: one temperature and one CO2 PID per room.
import json
import logging
import os
import time
from datetime import datetime
from urllib.parse import quote

import paho.mqtt.client as mqtt
import requests
from paho.mqtt.client import CallbackAPIVersion

from control_safety import ActuatorAckMonitor, SensorHealthMonitor
from room_config import load_simulated_rooms


CONNECT_RETRY_SECONDS = 2
HEALTH_CHECK_INTERVAL_SECONDS = 1
BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = 1883
OCCUPANCY_URL = os.getenv("OCCUPANCY_URL", "http://127.0.0.1:8081").rstrip("/")
DEFAULT_SET_TEMP = 21
DEFAULT_NIGHT_SET_TEMP = 17

# kp in W/°C (or W/ppm), ki in W/(unit·s), kd in W·s/unit.
CONTROLLER_SETTINGS = {
    "temp": {"setpoint": DEFAULT_SET_TEMP, "kp": 1000.0, "ki": 10.0, "kd": 0.0, "max_watts": 30000.0},
    "co2": {"setpoint": 900.0, "kp": 5.0, "ki": 0.001, "kd": 0.0, "max_watts": 600.0},
}


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


def label(controller):
    return f"{controller['room']} {controller['sensor_type']}"


def configured_setpoint(controller):
    if controller["sensor_type"] == "temp":
        return current_setpoint()
    return controller["configured_setpoint"]


def update_setpoint(client, controller, force=False):
    setpoint = configured_setpoint(controller)
    regulator = controller["regulator"]
    if force or regulator.setpoint != setpoint:
        regulator.setpoint = setpoint
        if controller["sensor_type"] == "temp":
            client.publish(
                controller["send_topic"],
                json.dumps({"set_temp": str(setpoint)}),
            )
        logging.info("Setpoint changed to %s for %s", setpoint, label(controller))


def build_controller(level, room, sensor_type):
    settings = CONTROLLER_SETTINGS[sensor_type]
    topic_prefix = f"{level}/{quote(room, safe='')}/{sensor_type}"
    return {
        "room": room,
        "listen_topic": f"{topic_prefix}/dec",
        "send_topic": f"{topic_prefix}/ac",
        "ack_topic": f"{topic_prefix}/actuator-status",
        "regulator": PIDRegulator(
            setpoint=settings["setpoint"],
            kp=settings["kp"],
            ki=settings["ki"],
            kd=settings["kd"],
            max_output=settings["max_watts"],
            reverse_action=sensor_type == "co2",
        ),
        "sensor_type": sensor_type,
        "configured_setpoint": settings["setpoint"],
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


def build_routes(controllers):
    routes = {}
    for controller in controllers:
        routes[controller["listen_topic"]] = controller
        routes[controller["ack_topic"]] = controller
    return routes


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("Ansluten till brokern!")
        client.subscribe([(topic, 0) for topic in userdata["routes"]])
        for controller in userdata["controllers"]:
            try:
                update_setpoint(client, controller, force=True)
            except (requests.RequestException, KeyError, TypeError, ValueError):
                logging.exception(
                    "Could not read occupancy simulator time for %s setpoint",
                    label(controller),
                )
    else:
        print(f"Anslutning misslyckades med kod: {reason_code}")


def on_message(client, userdata, msg):
    controller = userdata["routes"].get(msg.topic)
    if controller is None:
        logging.warning("Ignoring message on unexpected topic %s", msg.topic)
        return
    handle_message(client, controller, msg)


def handle_message(client, controller, msg):
    if msg.topic == controller["ack_topic"]:
        try:
            acknowledgement = json.loads(msg.payload.decode("utf-8"))
            accepted = controller["actuator_monitor"].acknowledge(
                acknowledgement["command_id"], acknowledgement["state"]
            )
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            logging.exception("Ignoring invalid %s actuator acknowledgement", label(controller))
            return
        if not accepted:
            logging.error("%s actuator failed to apply the latest command", label(controller))
        else:
            logging.info(
                "%s actuator command %s confirmed",
                label(controller),
                acknowledgement["command_id"],
            )
        return

    print(f"Mottaget meddelande på '{msg.topic}': {msg.payload.decode('utf-8')}")
    try:
        reading = json.loads(msg.payload.decode("utf-8"))
        measured_value = float(reading["value"])
        controller["sensor_monitor"].observe(
            measured_value, time.monotonic()
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        logging.exception("Ignoring invalid %s reading", label(controller))
        return

    failure_reason = controller["sensor_monitor"].failure_reason(time.monotonic())
    if failure_reason:
        if not controller["fail_safe"]:
            logging.error(
                "%s %s; entering fail-safe mode",
                label(controller),
                failure_reason,
            )
            publish_wattage(client, controller, safe_output(controller))
            controller["fail_safe"] = True
        return
    if controller["fail_safe"]:
        logging.info("%s sensor recovered; resuming PID control", label(controller))
        controller["fail_safe"] = False

    try:
        update_setpoint(client, controller)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        logging.exception("Ignoring %s reading because setpoint is unavailable", label(controller))
        return

    wattage = controller["regulator"].update(measured_value)
    publish_wattage(client, controller, wattage)
    print(f"{label(controller)} PID: {measured_value:.2f} -> {wattage:.2f} W")


def safe_output(controller):
    if controller["sensor_type"] == "co2":
        return controller["regulator"].max_output
    return 0.0


def publish_wattage(client, controller, wattage):
    command_id = controller["next_command_id"]
    controller["next_command_id"] += 1
    payload = {
        "watt": str(round(wattage, 2)),
        "command_id": command_id,
    }
    controller["last_command_payload"] = payload
    controller["actuator_monitor"].command_sent(
        command_id, payload["watt"], time.monotonic()
    )
    client.publish(controller["send_topic"], json.dumps(payload))


def health_watchdog(client, controller):
    now = time.monotonic()
    reason = controller["sensor_monitor"].failure_reason(now)
    if reason and not controller["fail_safe"]:
        logging.error("%s %s; entering fail-safe mode", label(controller), reason)
        publish_wattage(client, controller, safe_output(controller))
        controller["fail_safe"] = True

    monitor = controller["actuator_monitor"]
    if monitor.timed_out(now):
        logging.error(
            "%s actuator did not confirm command %s; retrying command",
            label(controller),
            monitor.command_id,
        )
        client.publish(
            controller["send_topic"],
            json.dumps(controller["last_command_payload"]),
        )
        monitor.mark_retry(now)


def main():
    logging.basicConfig(level=logging.INFO)
    controllers = [
        build_controller(str(room["floor"]), room["name"], sensor_type)
        for room in load_simulated_rooms()
        for sensor_type in CONTROLLER_SETTINGS
    ]
    userdata = {"controllers": controllers, "routes": build_routes(controllers)}
    print(f"Ansluter till MQTT-broker med {len(controllers)} regulatorer...")

    client = mqtt.Client(
        client_id=f"dec-{os.getpid()}",
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
            for controller in controllers:
                health_watchdog(client, controller)
            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nAvslutar...")
        client.loop_stop()
        client.disconnect()
    
if __name__ == "__main__":
    main()
