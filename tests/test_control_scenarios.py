import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_module(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


con_sim = load_module("con_sim", "con-sim.py")
con_dec = load_module("con_dec", "con-dec.py")
con_occ = load_module("con_occ", "con-occ.py")
from control_safety import ActuatorAckMonitor, SensorHealthMonitor


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload):
        self.messages.append((topic, json.loads(payload)))

    def subscribe(self, topic):
        pass


def controller_state(sensor_type="temp"):
    setpoint = 21 if sensor_type == "temp" else 900
    return {
        "room": "A109",
        "listen_topic": f"0/A109/{sensor_type}/dec",
        "send_topic": f"0/A109/{sensor_type}/ac",
        "ack_topic": f"0/A109/{sensor_type}/actuator-status",
        "sensor_type": sensor_type,
        "configured_setpoint": setpoint,
        "regulator": con_dec.PIDRegulator(
            setpoint, 100, 0, 0, 30000 if sensor_type == "temp" else 600,
            reverse_action=sensor_type == "co2",
        ),
        "sensor_monitor": SensorHealthMonitor(
            stale_after=15, stuck_samples=5, started_at=0
        ),
        "actuator_monitor": ActuatorAckMonitor(response_timeout=10),
        "next_command_id": 1,
        "last_command_payload": None,
        "fail_safe": False,
    }


class ControlScenarioTests(unittest.TestCase):
    def test_occupancy_publisher_reads_count_for_matching_room_and_level(self):
        state = {
            "sim": {
                "rooms": [
                    {"name": "A109", "level": "level0", "occupants": 12},
                    {"name": "A109", "level": "level1", "occupants": 99},
                ]
            }
        }

        self.assertEqual(con_occ.room_occupancy(state, "A109", "level0"), 12)

    def test_occupancy_publisher_rejects_missing_room(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            con_occ.room_occupancy(
                {"sim": {"rooms": []}}, "A109", "level0"
            )

    def test_occupancy_publisher_rejects_invalid_count(self):
        state = {
            "sim": {
                "rooms": [
                    {"name": "A109", "level": "level0", "occupants": -1}
                ]
            }
        }

        with self.assertRaisesRegex(ValueError, "invalid count"):
            con_occ.room_occupancy(state, "A109", "level0")

    def test_empty_room_reaches_temperature_setpoint_at_minus_10_c(self):
        setpoint = 21.0
        controller = con_dec.PIDRegulator(
            setpoint=setpoint,
            kp=1000,
            ki=10,
            kd=0,
            max_output=30000,
        )
        floor_area_m2 = 750.0
        wall_length_m = 16.0
        air_temperature = 15.0
        mass_temperature = 15.0
        first_reached_minute = None
        temperatures_after_reaching = []

        for step in range(48 * 60 // 5):
            wattage = controller.update(air_temperature, now=step * 5)
            air_temperature, mass_temperature = con_sim.simulate_step(
                air_temperature=air_temperature,
                mass_temperature=mass_temperature,
                volume_m3=floor_area_m2 * con_sim.ROOM_HEIGHT_METERS,
                floor_area_m2=floor_area_m2,
                exterior_wall_length_m=wall_length_m,
                outside_temperature=-10.0,
                setpoint=setpoint,
                heater_max_watts=wattage,
                duration_seconds=300,
                internal_gains_watts=0,
            )
            if air_temperature >= setpoint and first_reached_minute is None:
                first_reached_minute = step * 5
            if first_reached_minute is not None and step * 5 >= 42 * 60:
                temperatures_after_reaching.append(air_temperature)

        self.assertIsNotNone(first_reached_minute, "HVAC never reached its setpoint")
        self.assertLessEqual(first_reached_minute, 24 * 60)
        self.assertTrue(temperatures_after_reaching)
        self.assertTrue(
            all(setpoint - 1.0 <= value <= setpoint + 1.0
                for value in temperatures_after_reaching),
            f"Room did not hold setpoint: {temperatures_after_reaching[-5:]}",
        )

    def test_full_room_vent_recovers_below_1000_ppm_within_10_minutes(self):
        room_volume_m3 = 750.0 * con_sim.ROOM_HEIGHT_METERS
        full_occupancy = 94
        controller = con_dec.PIDRegulator(
            setpoint=900,
            kp=5,
            ki=0.001,
            kd=0,
            max_output=600,
            reverse_action=True,
        )
        co2_ppm = 1100.0
        recovery_minute = None
        levels = []

        for minute in range(10):
            ventilation_watts = controller.update(co2_ppm, now=minute * 60)
            co2_ppm = con_sim.simulate_co2_step(
                co2_ppm=co2_ppm,
                occupants=full_occupancy,
                ventilation_watts=ventilation_watts,
                room_volume_m3=room_volume_m3,
                duration_seconds=60,
            )
            levels.append(co2_ppm)
            if co2_ppm < 1000 and recovery_minute is None:
                recovery_minute = minute + 1

        self.assertIsNotNone(recovery_minute, f"CO2 remained high: {levels}")
        self.assertLessEqual(recovery_minute, 10)

    def test_crashed_or_stuck_sensor_enters_failsafe_and_recovers(self):
        for sensor_type, safe_wattage in (("temp", 0.0), ("co2", 600.0)):
            with self.subTest(sensor_type=sensor_type):
                state = controller_state(sensor_type)
                client = FakeClient()

                with patch.object(con_dec.time, "monotonic", return_value=20):
                    con_dec.health_watchdog(client, state)
                self.assertTrue(state["fail_safe"])
                self.assertEqual(float(client.messages[-1][1]["watt"]), safe_wattage)

                state = controller_state(sensor_type)
                client = FakeClient()
                with patch.object(con_dec.time, "monotonic", return_value=1), patch.object(
                    con_dec, "current_setpoint", return_value=state["configured_setpoint"]
                ):
                    for _ in range(5):
                        con_dec.handle_message(
                            client,
                            state,
                            type(
                                "Message",
                                (),
                                {
                                    "topic": state["listen_topic"],
                                    "payload": b'{"value":"20"}',
                                },
                            )(),
                        )
                self.assertTrue(state["fail_safe"])
                self.assertEqual(float(client.messages[-1][1]["watt"]), safe_wattage)

                state["sensor_monitor"].observe(19, now=2)
                message = type(
                    "Message",
                    (),
                    {
                        "topic": state["listen_topic"],
                        "payload": b'{"value":"19"}',
                    },
                )()
                with patch.object(con_dec.time, "monotonic", return_value=2), patch.object(
                    con_dec, "current_setpoint", return_value=state["configured_setpoint"]
                ):
                    con_dec.handle_message(client, state, message)
                self.assertFalse(state["fail_safe"])

    def test_stuck_or_crashed_actuator_is_detected_retried_and_recovers(self):
        state = controller_state("co2")
        state["sensor_monitor"].observe(800, now=0)
        client = FakeClient()
        command = {
            "watt": "600",
            "command_id": 8,
        }
        state["last_command_payload"] = command
        state["actuator_monitor"].command_sent(7, 600, now=0)
        state["actuator_monitor"].command_sent(8, 600, now=5)

        with patch.object(con_dec.time, "monotonic", return_value=11):
            con_dec.health_watchdog(client, state)
        self.assertEqual(client.messages[-1][1], command)
        self.assertFalse(state["actuator_monitor"].acknowledge(8, 0))

        state["sensor_monitor"].observe(800, now=11)
        with patch.object(con_dec.time, "monotonic", return_value=22):
            con_dec.health_watchdog(client, state)
        self.assertEqual(client.messages[-1][1], command)
        self.assertTrue(state["actuator_monitor"].acknowledge(8, 600))
        self.assertFalse(state["actuator_monitor"].timed_out(now=40))

        state["actuator_monitor"].command_sent(8, 250, now=40)
        self.assertTrue(state["actuator_monitor"].acknowledge(8, 250))

    def test_single_decision_maker_routes_each_room_to_its_own_controller(self):
        controllers = [
            con_dec.build_controller("0", room, sensor_type)
            for room in ("A107", "A108")
            for sensor_type in con_dec.CONTROLLER_SETTINGS
        ]
        userdata = {
            "controllers": controllers,
            "routes": con_dec.build_routes(controllers),
        }
        self.assertEqual(len(userdata["routes"]), 8)
        client = FakeClient()
        message = type(
            "Message",
            (),
            {"topic": "0/A108/co2/dec", "payload": b'{"value":"1200"}'},
        )()

        con_dec.on_message(client, userdata, message)

        self.assertEqual(len(client.messages), 1)
        topic, command = client.messages[0]
        self.assertEqual(topic, "0/A108/co2/ac")
        self.assertEqual(float(command["watt"]), 600.0)
        untouched = [c for c in controllers if c["listen_topic"] != message.topic]
        self.assertTrue(all(c["next_command_id"] == 1 for c in untouched))

    def test_simulator_keeps_other_rooms_running_when_one_room_fails(self):
        rooms = [
            {
                "name": name,
                "area": 50.0,
                "wall_length": 8.0,
                "air_temperature": 20.0,
                "mass_temperature": 20.0,
                "co2_ppm": 600.0,
                "temperature_topic": f"0/{name}/temp/sensor",
                "co2_topic": f"0/{name}/co2/sensor",
            }
            for name in ("A107", "A108")
        ]

        def fake_api_json(session, method, base_url, path):
            if "A107" in path:
                raise con_sim.requests.ConnectionError("buildsim unavailable")
            return {"state": "0", "value": "0"}

        with patch.object(con_sim, "api_json", side_effect=fake_api_json), \
                self.assertLogs(level="ERROR") as logs:
            messages = con_sim.simulate_rooms(
                None, rooms, outside_temperature=0.0, duration_seconds=300,
                noise_stddev=0, co2_noise_stddev=0,
            )

        self.assertIn("A107", logs.output[0])
        self.assertEqual(
            [message["topic"] for message in messages],
            ["0/A108/temp/sensor", "0/A108/co2/sensor"],
        )
        self.assertEqual(rooms[0]["air_temperature"], 20.0)
        self.assertLess(rooms[1]["air_temperature"], 20.0)


if __name__ == "__main__":
    unittest.main()
