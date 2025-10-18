#!/bin/bash

#export P2PD_DEBUG=1

n="${MONITOR_WORKER_NO:-100}"

echo "Starting dealer server"
python3 -m p2pd_server_monitor.dealer --log_path="/opt/p2pd_monitor/dealer.log" --py_p2pd_monitor &

sleep 5 # Wait for dealer server to start.

for i in $(seq 1 $n); do
    echo "Starting worker $i"
    python3 -m p2pd_server_monitor.worker \
        --log_path="/opt/p2pd_monitor/worker_$i.log" \
        --py_p2pd_monitor \
        >> "/opt/p2pd_monitor/worker_$i.log" 2>&1 &
done

wait

