# En sim
import argparse
import paho.mqtt.publish as publish
import json
import logging
import math
import os
import random
import requests
from datetime import datetime, time, timedelta
from pathlib import Path
from time import sleep
from urllib.parse import quote


BASE = os.getenv("BUILDSIM_URL", "http://127.0.0.1:9090/")
BASE_OCC = os.getenv("OCCUPANCY_URL", "http://127.0.0.1:8081/")


default_set_temp=21

DATA_DIR = Path(__file__).resolve().parent / "JSON files"
REQUEST_TIMEOUT = 10
POLL_INTERVAL_SECONDS = 0.5
ROOM_HEIGHT_METERS = 3.0
AIR_DENSITY_KG_PER_M3 = 1.225
AIR_HEAT_CAPACITY_J_PER_KG_K = 1000.0
EXTERIOR_WALL_U_VALUE_W_PER_M2_K = 0.25
VENTILATION_AIR_CHANGES_PER_HOUR = 0.5
THERMAL_MASS_CAPACITY_J_PER_M2_K = 165_000.0
AIR_MASS_COUPLING_W_PER_M2_K = 8.0
SENSIBLE_HEAT_PER_OCCUPANT_W = 75.0
OUTDOOR_CO2_PPM = 420.0
CO2_GENERATION_M3_PER_SECOND_PER_PERSON = 0.005 / 1000
MAX_VENTILATION_WATTS = 600.0
MAX_VENTILATION_AIR_CHANGES_PER_HOUR = 3.0

def parse_args():
    parser = argparse.ArgumentParser(description="Simulate room temperatures.")
    parser.add_argument("--level", default="0")
    parser.add_argument("--room", default="A109")
    parser.add_argument("--timestep-minutes", type=float, default=5)
    parser.add_argument("--temperature", type=float, default=25)
    parser.add_argument("--noise-stddev", type=float, default=0.2)
    parser.add_argument("--co2-noise-stddev", type=float, default=10.0)
    return parser.parse_args()


def api_json(session, method, base_url, path):
    response = session.request(
        method,
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def wait_for_api_json(session, path, description):
    while True:
        try:
            return api_json(session, "GET", BASE, path)
        except requests.RequestException as error:
            logging.warning("Waiting for %s: %s", description, error)
            sleep(POLL_INTERVAL_SECONDS)


def load_json(path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def prepare_weather(weather_rows):
    weather_by_day = {}
    for row in weather_rows:
        day = row["Day"]
        observed_at = time.fromisoformat(row["Time"])
        temperature = float(row["Temperature"])
        weather_by_day.setdefault(day, []).append((observed_at, temperature))

    for observations in weather_by_day.values():
        observations.sort(key=lambda observation: observation[0])
    return weather_by_day


def outside_temperature_at(weather_by_day, timestamp):
    observations = weather_by_day.get(timestamp.strftime("%A"))
    if not observations:
        raise ValueError(f"No weather observations for {timestamp.strftime('%A')}")

    current_time = timestamp.time()
    if current_time <= observations[0][0]:
        return observations[0][1]
    if current_time >= observations[-1][0]:
        return observations[-1][1]

    for (before_time, before_temp), (after_time, after_temp) in zip(
        observations, observations[1:]
    ):
        if before_time <= current_time <= after_time:
            span = (
                datetime.combine(timestamp.date(), after_time)
                - datetime.combine(timestamp.date(), before_time)
            ).total_seconds()
            elapsed = (
                datetime.combine(timestamp.date(), current_time)
                - datetime.combine(timestamp.date(), before_time)
            ).total_seconds()
            fraction = elapsed / span
            return before_temp + fraction * (after_temp - before_temp)

    raise ValueError(f"Could not interpolate weather at {timestamp}")


def state_time(state):
    return datetime.fromisoformat(state["sim"]["clock"]["time"])


def wait_for_next_timestep(session, previous_time, timestep):
    interval_start = previous_time
    while True:
        state = api_json(session, "GET", BASE_OCC, "api/state")
        current_time = state_time(state)
        if current_time < interval_start:
            interval_start = current_time
        elif current_time - interval_start >= timestep:
            return interval_start, current_time
        sleep(POLL_INTERVAL_SECONDS)


def room_occupancy(session, room):
    sensor_id = quote(f"{room}-occupancy", safe="")
    path = f"api/sensors/{sensor_id}"
    sensor = api_json(session, "GET", BASE, path)
    occupants = int(sensor["value"])
    if occupants < 0:
        raise ValueError(f"Occupancy sensor for {room} returned a negative count")
    return occupants


def simulate_step(
    air_temperature,
    mass_temperature,
    volume_m3,
    floor_area_m2,
    exterior_wall_length_m,
    outside_temperature,
    setpoint,
    heater_max_watts,
    duration_seconds,
    internal_gains_watts=0.0,
):
    if volume_m3 <= 0 or floor_area_m2 <= 0:
        raise ValueError("Room volume and floor area must be positive")
    if duration_seconds <= 0:
        raise ValueError("Timestep duration must be positive")

    air_capacity = (
        AIR_DENSITY_KG_PER_M3 * volume_m3 * AIR_HEAT_CAPACITY_J_PER_KG_K
    )
    mass_capacity = floor_area_m2 * THERMAL_MASS_CAPACITY_J_PER_M2_K
    exterior_wall_area = max(0.0, exterior_wall_length_m) * ROOM_HEIGHT_METERS
    fabric_conductance = EXTERIOR_WALL_U_VALUE_W_PER_M2_K * exterior_wall_area
    ventilation_conductance = (
        AIR_DENSITY_KG_PER_M3
        * AIR_HEAT_CAPACITY_J_PER_KG_K
        * volume_m3
        * VENTILATION_AIR_CHANGES_PER_HOUR
        / 3600
    )
    air_mass_conductance = floor_area_m2 * AIR_MASS_COUPLING_W_PER_M2_K
    total_outside_conductance = fabric_conductance + ventilation_conductance

    # Substeps keep this explicit two-node heat balance stable at larger API timesteps.
    substep_count = max(1, int(duration_seconds // 60) + 1)
    substep_seconds = duration_seconds / substep_count
    for _ in range(substep_count):
        outside_loss = total_outside_conductance * (
            air_temperature - outside_temperature
        )
        mass_exchange = air_mass_conductance * (mass_temperature - air_temperature)
        #required_heating = (
        #    (setpoint - air_temperature) * air_capacity / substep_seconds
        #    - mass_exchange
        #    - internal_gains_watts
        #    + outside_loss
        #)
        #heater_watts = (
        #    min(heater_max_watts, max(0.0, required_heating))
        #    if air_temperature < setpoint
        #    else 0.0
        #)
        heater_watts = heater_max_watts
        air_temperature += (
            heater_watts
            + internal_gains_watts
            - outside_loss
            + mass_exchange
        ) * substep_seconds / air_capacity
        mass_temperature -= (
            mass_exchange * substep_seconds / mass_capacity
        )

    return air_temperature, mass_temperature


def simulate_co2_step(
    co2_ppm,
    occupants,
    ventilation_watts,
    room_volume_m3,
    duration_seconds,
):
    if room_volume_m3 <= 0 or duration_seconds <= 0:
        raise ValueError("Room volume and timestep duration must be positive")
    if occupants < 0 or ventilation_watts < 0:
        raise ValueError("Occupants and ventilation power must be non-negative")

    ventilation_fraction = min(ventilation_watts / MAX_VENTILATION_WATTS, 1.0)
    air_changes_per_hour = (
        ventilation_fraction * MAX_VENTILATION_AIR_CHANGES_PER_HOUR
    )
    air_exchange_rate = air_changes_per_hour / 3600
    co2_generation_ppm_per_second = (
        occupants
        * CO2_GENERATION_M3_PER_SECOND_PER_PERSON
        / room_volume_m3
        * 1_000_000
    )

    if air_exchange_rate == 0:
        return co2_ppm + co2_generation_ppm_per_second * duration_seconds

    equilibrium_ppm = (
        OUTDOOR_CO2_PPM
        + co2_generation_ppm_per_second / air_exchange_rate
    )
    return equilibrium_ppm + (co2_ppm - equilibrium_ppm) * math.exp(
        -air_exchange_rate * duration_seconds
    )


BROKER = os.getenv("MQTT_HOST", "localhost")
PORT = 1883
    
def main():
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    timestep = timedelta(minutes=args.timestep_minutes)
    if timestep.total_seconds() <= 0:
        raise ValueError("Timestep must be positive")
    if args.noise_stddev < 0:
        raise ValueError("Noise standard deviation must be non-negative")
    if args.co2_noise_stddev < 0:
        raise ValueError("CO2 noise standard deviation must be non-negative")

    weather_data = load_json(DATA_DIR / "Weather.json")
    room_data = load_json(DATA_DIR / "rooms.json")
    weather_by_day = prepare_weather(weather_data["weather"])
    configured_room = next(
        (
            item
            for item in room_data["rooms"]
            if item["name"] == args.room and str(item["floor"]) == str(args.level)
        ),
        None,
    )
    if configured_room is None:
        raise ValueError(f"Room {args.room!r} on level {args.level!r} is not configured")

    session = requests.Session()
    floor = api_json(
        session,
        "GET",
        BASE,
        f"api/building/floors/level{args.level}",
    )
    floor_room = next(
        (item for item in floor["rooms"] if item["name"] == args.room),
        None,
    )
    if floor_room is None:
        raise ValueError(f"Room {args.room!r} not found in the building API")

    room = {
        "name": args.room,
        "area": float(floor_room["area"]),
        "wall_length": float(configured_room["walls"]),
        "air_temperature": args.temperature,
        "mass_temperature": args.temperature,
    }
    sensor = wait_for_api_json(
        session,
        f"api/sensors/{quote(f'{args.room}-temp', safe='')}",
        f"{args.room} temperature sensor",
    )
    room["air_temperature"] = float(sensor["value"])
    room["mass_temperature"] = room["air_temperature"]

    co2_sensor = wait_for_api_json(
        session,
        f"api/sensors/{quote(f'{args.room}-co2', safe='')}",
        f"{args.room} CO2 sensor",
    )
    co2_ppm = max(OUTDOOR_CO2_PPM, float(co2_sensor["value"]))
    wait_for_api_json(
        session,
        f"api/actuators/{quote(f'{args.room}-watt', safe='')}",
        f"{args.room} HVAC actuator",
    )
    wait_for_api_json(
        session,
        f"api/actuators/{quote(f'{args.room}-vent', safe='')}",
        f"{args.room} ventilation actuator",
    )
    wait_for_api_json(
        session,
        f"api/sensors/{quote(f'{args.room}-occupancy', safe='')}",
        f"{args.room} occupancy sensor",
    )

    topic_room = quote(args.room, safe="")
    temperature_topic = f"{args.level}/{topic_room}/temp/sensor"
    co2_topic = f"{args.level}/{topic_room}/co2/sensor"
    simulation_time = state_time(api_json(session, "GET", BASE_OCC, "api/state"))
    print(f"Waiting for {timestep} of occupancy-simulation time")
    try:
        while True:
            interval_start, next_time = wait_for_next_timestep(
                session, simulation_time, timestep
            )
            duration_seconds = (next_time - interval_start).total_seconds()
            simulation_time = next_time

            wattage = float(
                api_json(
                    session,
                    "GET",
                    BASE,
                    f"api/actuators/{args.room}-watt",
                )["state"]
            )
            ventilation_wattage = float(
                api_json(
                    session,
                    "GET",
                    BASE,
                    f"api/actuators/{args.room}-vent",
                )["state"]
            )
            occupants = room_occupancy(session, args.room)
            outside_temperature = outside_temperature_at(weather_by_day, next_time)
            room["air_temperature"], room["mass_temperature"] = simulate_step(
                air_temperature=room["air_temperature"],
                mass_temperature=room["mass_temperature"],
                volume_m3=room["area"] * ROOM_HEIGHT_METERS,
                floor_area_m2=room["area"],
                exterior_wall_length_m=room["wall_length"],
                outside_temperature=outside_temperature,
                setpoint=default_set_temp,
                heater_max_watts=wattage,
                duration_seconds=duration_seconds,
                internal_gains_watts=occupants * SENSIBLE_HEAT_PER_OCCUPANT_W,
            )

            noisy_temperature = room["air_temperature"] + random.gauss(
                0, args.noise_stddev
            )
            co2_ppm = simulate_co2_step(
                co2_ppm=co2_ppm,
                occupants=occupants,
                ventilation_watts=ventilation_wattage,
                room_volume_m3=room["area"] * ROOM_HEIGHT_METERS,
                duration_seconds=duration_seconds,
            )
            noisy_co2 = max(
                OUTDOOR_CO2_PPM,
                co2_ppm + random.gauss(0, args.co2_noise_stddev),
            )
            publish.single(
                topic=temperature_topic,
                payload=json.dumps({"value": str(round(noisy_temperature, 2))}),
                hostname=BROKER,
                port=PORT,
            )
            publish.single(
                topic=co2_topic,
                payload=json.dumps({"value": str(round(noisy_co2, 1))}),
                hostname=BROKER,
                port=PORT,
            )
            print(
                f"{next_time.isoformat()} | {occupants} occupants | "
                f"{wattage:.0f} W HVAC | {ventilation_wattage:.0f} W vent | "
                f"{noisy_temperature:.2f} °C | {noisy_co2:.1f} ppm CO2"
            )
    except KeyboardInterrupt:
        print("\nStopping simulation.")
    
if __name__ == "__main__":
    main()