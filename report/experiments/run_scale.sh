#!/usr/bin/env bash
# Scaling run: enable the first N rooms that resolve in both BuildSim and the
# occupancy simulator, start the stack, wait 150 s after the first step, measure.
# Usage: experiments/run_scale.sh <rooms> <output-dir>
# Rewrites "JSON files/rooms.json" and services-compose.yaml: back them up first.
set -u
N=$1
OUT=$(realpath "$2")
mkdir -p "$OUT"
cd "$(dirname "$0")/../.."
DC="docker compose -f compose.yaml -f services-compose.yaml"
ev() { echo "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ) $*" | tee -a "$OUT/events.log"; }

python report/experiments/select_rooms.py "$N"   # needs BuildSim + occupancy sim running
python yaml_generate.py > "$OUT/generate.txt"
# Build the shared image once: with ~200 services sharing one build section,
# `up --build` failed in BuildKit at 40 rooms ("no such job").
$DC build sim > "$OUT/build.log" 2>&1
ev "up start"
$DC up -d > "$OUT/up.log" 2>&1 || { ev "up FAILED"; exit 1; }
ev "up done"
# The previous simulator's output must not count as this run's first step.
until $DC logs --no-log-prefix sim 2>/dev/null | grep -q "Simulating $N rooms"; do sleep 2; done
until $DC logs --no-log-prefix sim 2>/dev/null | grep -q "outside"; do sleep 2; done
ev "first sim step"
sleep 150
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' > "$OUT/stats.txt"
docker run --rm alpine free -m > "$OUT/free.txt"
ev "stats"
$DC logs -t --no-color --no-log-prefix sim > "$OUT/log_sim.txt" 2>&1
$DC logs -t --no-color --no-log-prefix dec > "$OUT/log_dec.txt" 2>&1
for c in $(docker ps -aq --filter label=com.docker.compose.project=d7065e); do
  docker inspect -f '{{.Name}} restarts={{.RestartCount}} status={{.State.Status}}' "$c"
done > "$OUT/containers.txt"
ev "done"
