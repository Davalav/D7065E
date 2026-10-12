import math


class SensorHealthMonitor:
    def __init__(self, stale_after=15.0, stuck_samples=5, started_at=0.0):
        if stale_after <= 0 or stuck_samples < 2:
            raise ValueError("Sensor timeout must be positive and stuck threshold at least two")
        self.stale_after = stale_after
        self.stuck_samples = stuck_samples
        self.started_at = started_at
        self.last_value = None
        self.last_received_at = None
        self.repeated_samples = 0

    def observe(self, value, now):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Sensor reading must be finite")
        if self.last_value is not None and value == self.last_value:
            self.repeated_samples += 1
        else:
            self.last_value = value
            self.repeated_samples = 1
        self.last_received_at = now

    def failure_reason(self, now):
        reference_time = (
            self.started_at
            if self.last_received_at is None
            else self.last_received_at
        )
        if now - reference_time > self.stale_after:
            return "sensor data is stale"
        if self.repeated_samples >= self.stuck_samples:
            return "sensor reading is stuck"
        return None


class ActuatorAckMonitor:
    def __init__(self, response_timeout=10.0):
        if response_timeout <= 0:
            raise ValueError("Actuator response timeout must be positive")
        self.response_timeout = response_timeout
        self.command_id = None
        self.command_value = None
        self.sent_at = None

    def command_sent(self, command_id, value, now):
        if self.sent_at is None:
            self.sent_at = now
        self.command_id = command_id
        self.command_value = float(value)

    def acknowledge(self, command_id, actual_value):
        if command_id != self.command_id:
            return False
        try:
            actual_value = float(actual_value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(actual_value) or not math.isclose(
            actual_value, self.command_value, rel_tol=0.0, abs_tol=0.01
        ):
            return False
        self.command_id = None
        self.command_value = None
        self.sent_at = None
        return True

    def timed_out(self, now):
        return (
            self.sent_at is not None
            and now - self.sent_at > self.response_timeout
        )

    def mark_retry(self, now):
        if self.command_id is not None:
            self.sent_at = now
