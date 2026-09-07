import os
import time
import requests

DEFAULT_BASE_URL = "http://127.0.0.1:9090"


def step(session, base_url, temp):
    # 1. Läs heating setpoint från BuildSim
    try:
        response = session.get(
            f"{base_url}/api/actuators/A109-set",
            timeout=5
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"cannot reach BuildSim at {base_url}: {e}"
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"cannot read actuator: {response.status_code} "
            f"(did you run setup?)"
        )

    try:
        current = response.json()
    except ValueError as e:
        raise RuntimeError(f"decode actuator: {e}")

    try:
        setpoint = float(current["state"])
    except (KeyError, ValueError, TypeError) as e:
        state = current.get("state")
        raise RuntimeError(
            f"actuator A109-set has invalid state {state!r}: {e}"
        )

    # 2. Enkel fysik:
    # flytta 20 % av vägen mot setpoint
    temp += 0.2 * (setpoint - temp)

    # 3. Skriv tillbaka den nya temperaturen
    body = {
        "data_type": "text",
        "value": f"{temp:.1f}"
    }

    try:
        response = session.put(
            f"{base_url}/api/sensors/A109-temp/value",
            json=body,
            timeout=5
        )
    except requests.RequestException as e:
        raise RuntimeError(
            f"cannot write to BuildSim: {e}"
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"BuildSim rejected the write "
            f"({response.status_code}), did you run setup?"
        )

    return setpoint, temp


def main():
    base_url = os.getenv("BUILDSIM_URL", "").rstrip("/")

    if not base_url:
        base_url = DEFAULT_BASE_URL

    session = requests.Session()

    temp = 18.0

    while True:
        try:
            setpoint, temp = step(
                session,
                base_url,
                temp
            )

            print(
                f"setpoint {setpoint:.1f} "
                f"-> temp {temp:.1f}"
            )

            time.sleep(2)

        except RuntimeError as e:
            print(f"ERROR: {e}")
            break


if __name__ == "__main__":
    main()