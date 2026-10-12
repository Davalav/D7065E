import json
import logging
import os
from datetime import datetime, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


BUILD_SIM_URL = os.getenv("BUILDSIM_URL", "http://127.0.0.1:9090").rstrip("/")
OCCUPANCY_URL = os.getenv("OCCUPANCY_URL", "http://127.0.0.1:8081").rstrip("/")
LISTEN = ("0.0.0.0", int(os.getenv("METRICS_PORT", "9101")))
REQUEST_TIMEOUT = 5
DATA_DIR = Path(__file__).resolve().parent / "JSON files"
WEATHER_PATH = DATA_DIR / "Weather.json"

METRIC_INFO = (
    ("building_outside_temperature_celsius", "Outside air temperature in Celsius."),
    ("building_occupancy_sim_time_seconds", "Occupancy simulator clock as Unix time in seconds."),
    ("room_power_consumption_watts", "Room HVAC actuator power setting in watts."),
    ("room_temperature_celsius", "Room temperature sensor reading in Celsius."),
    ("room_set_temperature_celsius", "Room HVAC temperature setpoint in Celsius."),
    ("room_co2_ppm", "Room carbon dioxide sensor reading in parts per million."),
    ("room_occupancy_people", "Number of people reported by the room occupancy sensor."),
)


def get_json(url):
    with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def load_weather():
    with WEATHER_PATH.open("r", encoding="utf-8") as source:
        rows = json.load(source)["weather"]
    weather = {}
    for row in rows:
        weather.setdefault(row["Day"], []).append(
            (time.fromisoformat(row["Time"]), float(row["Temperature"]))
        )
    for observations in weather.values():
        observations.sort(key=lambda item: item[0])
    return weather


def outside_temperature_at(weather, timestamp):
    observations = weather.get(timestamp.strftime("%A"))
    if not observations:
        raise ValueError(f"No weather data for {timestamp.strftime('%A')}")
    now = timestamp.timetz().replace(tzinfo=None)
    if now <= observations[0][0]:
        return observations[0][1]
    if now >= observations[-1][0]:
        return observations[-1][1]
    for (before_time, before_value), (after_time, after_value) in zip(
        observations, observations[1:]
    ):
        if before_time <= now <= after_time:
            span = (after_time.hour * 3600 + after_time.minute * 60 + after_time.second) - (
                before_time.hour * 3600 + before_time.minute * 60 + before_time.second
            )
            elapsed = (now.hour * 3600 + now.minute * 60 + now.second) - (
                before_time.hour * 3600 + before_time.minute * 60 + before_time.second
            )
            return before_value + (after_value - before_value) * elapsed / span
    raise ValueError(f"Could not interpolate weather at {timestamp}")


def metric_samples(equipment, clock, weather):
    values = {
        "building_outside_temperature_celsius": [],
        "building_occupancy_sim_time_seconds": [],
    }
    timestamp = datetime.fromisoformat(clock["time"])
    values["building_outside_temperature_celsius"].append(
        ((), outside_temperature_at(weather, timestamp))
    )
    values["building_occupancy_sim_time_seconds"].append(((), timestamp.timestamp()))

    for item in equipment:
        room = item.get("room")
        if not room:
            continue
        for sensor in item.get("sensors") or []:
            metric_name = {
                "temperature": "room_temperature_celsius",
                "co2": "room_co2_ppm",
                "occupancy": "room_occupancy_people",
            }.get(sensor.get("type"))
            if metric_name is None:
                continue
            try:
                value = float(sensor["value"])
            except (KeyError, TypeError, ValueError):
                logging.warning("Skipping invalid value for sensor %s", sensor.get("id"))
                continue
            values.setdefault(metric_name, []).append(((("room", room),), value))

        for actuator in item.get("actuators") or []:
            metric_name = {
                "wattage": "room_power_consumption_watts",
                "setpoint": "room_set_temperature_celsius",
            }.get(actuator.get("type"))
            if metric_name is None:
                continue
            try:
                value = float(actuator["state"])
            except (KeyError, TypeError, ValueError):
                logging.warning("Skipping invalid state for actuator %s", actuator.get("id"))
                continue
            values.setdefault(metric_name, []).append(((("room", room),), value))
    return values


def format_metrics(samples):
    lines = []
    for name, help_text in METRIC_INFO:
        lines.extend((f"# HELP {name} {help_text}", f"# TYPE {name} gauge"))
        for labels, value in samples.get(name, []):
            label_text = ""
            if labels:
                escaped = labels[0][1].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                label_text = f'{{room="{escaped}"}}'
            lines.append(f"{name}{label_text} {value}")
    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    weather = load_weather()

    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        try:
            equipment = get_json(f"{BUILD_SIM_URL}/api/equipment")
            state = get_json(f"{OCCUPANCY_URL}/api/state")
            body = format_metrics(
                metric_samples(equipment, state["sim"]["clock"], self.weather)
            ).encode("utf-8")
        except (OSError, URLError, ValueError, KeyError, TypeError) as error:
            logging.exception("Failed to collect building metrics")
            self.send_error(503, str(error))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        logging.info("%s - %s", self.address_string(), format_string % args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer(LISTEN, MetricsHandler)
    logging.info("Prometheus exporter listening on %s:%s", *LISTEN)
    server.serve_forever()
