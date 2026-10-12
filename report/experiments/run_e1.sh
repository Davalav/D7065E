#!/usr/bin/env bash
# E1: nominal run (~40 real minutes = ~40 simulated hours at factor 60), then
# fault injection E2-E5. Usage: experiments/run_e1.sh <output-dir>
# Grafana is started with anonymous viewing (override file in <output-dir>) only
# so that the dashboard screenshot needs no login.
set -u
OUT=$(realpath "$1")
mkdir -p "$OUT/chrome-profile"
CHROME=${CHROME:-"/c/Program Files/Google/Chrome/Application/chrome.exe"}
cd "$(dirname "$0")/../.."
cat > "$OUT/grafana-anon.yaml" <<'YAML'
services:
  grafana:
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: "Viewer"
YAML
DC="docker compose -f compose.yaml -f services-compose.yaml -f $OUT/grafana-anon.yaml"
ev() { echo "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ) $*" | tee -a "$OUT/events.log"; }
winpath() { if command -v cygpath > /dev/null; then cygpath -w "$1"; else echo "$1"; fi; }
shot() {  # shot <url> <file> <virtual-time-budget-ms>
  "$CHROME" --headless=new --user-data-dir="$(winpath "$OUT/chrome-profile")" --hide-scrollbars \
    --use-angle=swiftshader --enable-unsafe-swiftshader --window-size=1600,1300 \
    --virtual-time-budget="$3" --screenshot="$(winpath "$OUT/$2")" "$1" > /dev/null 2>&1
}

ev "up start"
$DC up --build -d > "$OUT/up.log" 2>&1
ev "up done"
until $DC logs --no-log-prefix sim 2>/dev/null | grep -q "outside"; do sleep 2; done
T0=$(date -u +%s)
ev "T0 first sim step"
sleep 1200
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' > "$OUT/stats_20min.txt"
ev "stats captured"
sleep 1020
ev "screenshots"
shot "http://localhost:3000/d/building-simulation/?orgId=1&kiosk&from=now-40m&to=now" grafana.png 20000
shot "http://127.0.0.1:9090/" buildsim.png 20000
shot "http://127.0.0.1:8081/" occupancy.png 15000
sleep 60
ev "E2 stop sensor-r009-a110"
$DC stop sensor-r009-a110
sleep 60
ev "E2 start sensor-r009-a110"
$DC start sensor-r009-a110
sleep 90
ev "E3 stop hvac-r008-a109"
$DC stop hvac-r008-a109
sleep 40
ev "E3 start hvac-r008-a109"
$DC start hvac-r008-a109
sleep 90
ev "E4 kill dec"
$DC kill dec
sleep 20
STATE=$(docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' d7065e-dec-1)
ev "E4 dec after 20 s: $STATE"
case "$STATE" in running*) ;; *) ev "E4 start dec (manual)"; $DC start dec ;; esac
sleep 90
ev "E5 stop mosquitto"
$DC stop mosquitto
sleep 20
ev "E5 start mosquitto"
$DC start mosquitto
sleep 120
ev "collect"
for s in sim dec occupancysim metrics-exporter sensor-r009-a110 hvac-r008-a109 mosquitto occ-r007-a108; do
  $DC logs -t --no-color --no-log-prefix "$s" > "$OUT/log_$s.txt" 2>&1
done
$DC logs -t --no-color > "$OUT/log_all.txt" 2>&1
for c in dec sim sensor-r009-a110 hvac-r008-a109 mosquitto; do
  docker inspect -f '{{.Name}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} restarts={{.RestartCount}} status={{.State.Status}}' "d7065e-$c-1"
done > "$OUT/inspect.txt"
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' > "$OUT/stats_end.txt"
END=$(date -u +%s)
for m in room_temperature_celsius room_co2_ppm room_power_consumption_watts room_ventilation_command_watts \
         room_set_temperature_celsius room_occupancy_people building_outside_temperature_celsius building_occupancy_sim_time_seconds; do
  curl -s "http://127.0.0.1:9091/api/v1/query_range?query=$m&start=$T0&end=$END&step=5" > "$OUT/prom_$m.json"
done
ev "done"
