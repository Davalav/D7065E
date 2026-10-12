# D7065E

## Starta Buildsim (från D7065E-code):
<!-- ./../D7065E-buildsim/buildingsim/buildsim start --port 9090 -->
sudo docker compose up --build



## Simulera Alfa:
python build.py Alfa
python sim.py Alfa --delay-seconds 0

## Actuator:
python sensors.py Alfa

## Lecture occupancy publisher:
python con-occ.py

## Öppna databasen:
sqlit connect sqlite --file-path "data.db"

## Stäng
sudo docker compose down

## TODO
- Containerize(Dela upp i separata containers
- Actuator/Autonomous decision making agent
- Dashboard
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
publish to buildsim and occ

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