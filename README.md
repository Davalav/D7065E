# D7065E

## Starta Buildsim (från D7065E-code):
<!-- ./../D7065E-buildsim/buildingsim/buildsim start --port 9090 -->
sudo docker compose up --build

The occupancy simulator loads its startup parameters from `occupancy-config.json`,
which is mounted into the service by Compose.

## Monitoring dashboard

Compose starts Prometheus and Grafana alongside the simulation. Open Grafana at
http://localhost:3000 and sign in with `admin` / `admin` on first start. The
provisioned **Building / Building simulation** dashboard shows the scheduled
outside temperature and BuildSim room power, temperature, setpoint, CO₂, and
occupancy readings. The room selector filters the room panels; a metric is
shown when its corresponding sensor or actuator is present in BuildSim.

Prometheus is also available at http://localhost:9091. Graph samples use
system-time scrape timestamps so Grafana's time picker can display them; the
dashboard separately shows the occupancy simulator's displayed clock in
Swedish local time.
Prometheus uses temporary storage, so collected values are cleared whenever
its container is restarted. Grafana configuration remains in the
`grafana-data` volume.

Compose also starts a CO₂ sensor, PID controller, and ventilation actuator for
room A109. The room simulation models occupant CO₂ generation and ventilation
with outdoor air at 420 ppm; the controller targets 900 ppm and adjusts
ventilation between 0 and 600 watt-equivalent units (mapped to 0–3 air changes
per hour). Grafana shows that command separately from HVAC power consumption.

## Control scenario and failure tests

Run `python -m unittest discover -s tests -v` to check cold-weather heating,
full-room CO₂ recovery, and sensor/actuator fault handling. Missing or
unchanging sensor data triggers a fail-safe output (heating off, ventilation
fully open); sensor readings resume normal PID control after recovery.
Actuators confirm applied wattage to the controller. Missing or mismatched
acknowledgements are detected and the latest command is retried.

## Simulera Alfa:
python build.py Alfa
python sim.py Alfa --delay-seconds 0

## Actuator:
python sensors.py Alfa

## Lecture occupancy sensor:
python con-occ.py

## Öppna databasen:
sqlit connect sqlite --file-path "data.db"

## Stäng
sudo docker compose down

## TODO
- Containerize(Dela upp i separata containers
- Actuator/Autonomous decision making agent
- Project paper
- Test plan
- C4 context and container diagrams
- MQTT
- Kolla upp vad varje gör


## För ett rum
En container per sak:
- Sensor ->
- Decision making ->
- Actuator ->
- Simulation ->
- Sensor


## Bättre beskrivning
### sim
wait for 5 min in occ
get time from occ
read from buildsim
run physics timestep
send to sensor with noise

### occupancy sensor
wait for 5 min in occ
get time from occ
read from lecture file
write occupancy counts to occupancy sensors in buildsim

### sensor
receive from sim
publish
send to decision making

### decision making
receive from sensor
select output
send to actuator

### actuator
receive from decision making
publish to buildsim



## Project proposal
https://www.overleaf.com/project/6a982a1d1d7b32586fd50cae