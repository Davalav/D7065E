import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ROOMS_PATH = ROOT / "JSON files" / "rooms.json"
OUTPUT_PATH = ROOT / "services-compose.yaml"


def yaml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def service_block(name, command, environment, dependencies):
    lines = [
        f"  {name}:",
        "    <<: *python-service",
        f"    command: {json.dumps(command, ensure_ascii=False)}",
    ]
    if environment:
        lines.append("    environment:")
        lines.extend(
            f"      {key}: {yaml_string(value)}"
            for key, value in environment.items()
        )
    if dependencies:
        lines.append("    depends_on:")
        for dependency, condition in dependencies.items():
            lines.extend(
                [
                    f"      {dependency}:",
                    f"        condition: {condition}",
                ]
            )
    return "\n".join(lines)


def main():
    rooms = json.loads(ROOMS_PATH.read_text(encoding="utf-8"))["rooms"]
    services = []
    service_names = set()

    for index, room in enumerate(rooms):
        room_name = room["name"]
        level = str(room["floor"])
        slug = re.sub(r"[^a-z0-9]+", "-", room_name.lower()).strip("-")
        prefix = f"r{index:03d}-{slug}"
        names = {
            kind: f"{kind}-{prefix}"
            for kind in (
                "occ",
                "sensor",
                "sensor-co2",
                "hvac",
                "dec",
                "dec-co2",
                "vent",
                "sim",
            )
        }
        if service_names.intersection(names.values()):
            raise ValueError(f"Duplicate generated service name for {room_name!r}")
        service_names.update(names.values())

        room_args = ["--level", level, "--room", room_name]
        buildsim_ready = {"buildsim": "service_healthy"}
        mqtt_ready = {"mosquitto": "service_healthy"}
        occupancy_ready = {"occupancysim": "service_healthy"}

        services.extend(
            [
                service_block(
                    names["occ"],
                    ["python", "-u", "con-occ.py", *room_args],
                    {
                        "BUILDSIM_URL": "http://buildsim:9090/",
                        "OCCUPANCY_URL": "http://occupancysim:8081/",
                    },
                    buildsim_ready | occupancy_ready,
                ),
                service_block(
                    names["sensor"],
                    ["python", "-u", "con-sensor.py", *room_args],
                    {
                        "BUILDSIM_URL": "http://buildsim:9090/",
                        "MQTT_HOST": "mosquitto",
                    },
                    buildsim_ready | mqtt_ready,
                ),
                service_block(
                    names["sensor-co2"],
                    ["python", "-u", "con-sensor.py", "--type", "co2", *room_args],
                    {
                        "BUILDSIM_URL": "http://buildsim:9090/",
                        "MQTT_HOST": "mosquitto",
                    },
                    buildsim_ready | mqtt_ready,
                ),
                service_block(
                    names["hvac"],
                    ["python", "-u", "con-hvac.py", *room_args],
                    {
                        "BUILDSIM_URL": "http://buildsim:9090/",
                        "MQTT_HOST": "mosquitto",
                    },
                    buildsim_ready | mqtt_ready,
                ),
                service_block(
                    names["dec"],
                    [
                        "python", "-u", "con-dec.py", *room_args,
                        "--kp", "1000", "--ki", "10", "--kd", "0",
                        "--max-watts", "30000",
                    ],
                    {
                        "MQTT_HOST": "mosquitto",
                        "OCCUPANCY_URL": "http://occupancysim:8081",
                    },
                    mqtt_ready
                    | occupancy_ready
                    | {names["sensor"]: "service_started", names["hvac"]: "service_started"},
                ),
                service_block(
                    names["dec-co2"],
                    [
                        "python", "-u", "con-dec.py", "--type", "co2", *room_args,
                        "--setpoint", "900", "--kp", "5", "--ki", "0.001",
                        "--kd", "0",
                    ],
                    {"MQTT_HOST": "mosquitto"},
                    mqtt_ready
                    | {
                        names["sensor-co2"]: "service_started",
                        names["vent"]: "service_started",
                    },
                ),
                service_block(
                    names["vent"],
                    ["python", "-u", "con-vent.py", *room_args],
                    {
                        "BUILDSIM_URL": "http://buildsim:9090/",
                        "MQTT_HOST": "mosquitto",
                    },
                    buildsim_ready | mqtt_ready,
                ),
                service_block(
                    names["sim"],
                    ["python", "-u", "con-sim.py", *room_args],
                    {
                        "BUILDSIM_URL": "http://buildsim:9090/",
                        "OCCUPANCY_URL": "http://occupancysim:8081/",
                        "MQTT_HOST": "mosquitto",
                    },
                    buildsim_ready
                    | occupancy_ready
                    | {
                        names["occ"]: "service_started",
                        names["sensor"]: "service_started",
                        names["sensor-co2"]: "service_started",
                        names["hvac"]: "service_started",
                        names["vent"]: "service_started",
                        "mosquitto": "service_healthy",
                    },
                ),
            ]
        )

    content = "\n".join(
        [
            "# Generated by yaml_generate.py from JSON files/rooms.json.",
            "x-python-service: &python-service",
            "  image: d7065e-python:latest",
            "  build:",
            "    context: .",
            "    dockerfile: Dockerfile.python",
            "  restart: unless-stopped",
            "",
            "services:",
            *services,
            "",
        ]
    )
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {len(services)} room-specific services to {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
