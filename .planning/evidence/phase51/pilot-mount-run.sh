#!/bin/bash
# Run inside a new private mount/PID namespace under systemd resource limits.
set -euo pipefail
scratch=$1
run=$2
backend=$3
script=$4
sha=$5
area="$scratch/runs/$run"
seed="$scratch/seed"
merged="$area/merged"
mkdir -p "$area"/{merged,upper,work,out}
chown 1000:1000 "$area"/{upper,work,out}
# Native code sees real filesystem free space in the overlay's upper filesystem.
mount --bind "$seed" "$seed"
mount -o remount,bind,ro "$seed"
live=/home/ubuntu/Neraium-Poly
mount --bind "$live" "$live"
mount -o remount,bind,ro "$live"
mount -t overlay overlay -o "lowerdir=$seed,upperdir=$area/upper,workdir=$area/work,index=off,metacopy=off" "$merged"
# Walkability for ubuntu applies to the mounted view and output directory.
# The original seed pathname is separately made inaccessible to the worker.
mount -t tmpfs -o mode=000,size=4k tmpfs "$seed"
cd "$area/out"
launch_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
exec setpriv --reuid=1000 --regid=1000 --clear-groups --no-new-privs --bounding-set=-all env -i \
    PATH=/usr/bin:/bin HOME="$area/out" PYTHONPATH="$backend" PAPER_TRADING=true LIVE_TRADING_ENABLED=false \
    NERAIUM_SHADOW_RESEARCH=false NERAIUM_DEPLOYED_SOURCE="$sha" PHASE51_LAUNCH_NS="$launch_ns" PYTHONDONTWRITEBYTECODE=1 \
    "$live/.venv/bin/python" "$script" "$merged" "$scratch/baseline.json" "$area/out"
