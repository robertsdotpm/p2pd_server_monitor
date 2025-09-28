#!/bin/bash

n="${MONITOR_WORKER_NO:-5}"

echo "Starting dealer server"
python3 -m p2pd_server_monitor.dealer_server --log_path=dealer.log --py_p2pd_monitor &

for i in $(seq 1 $n); do
    echo "Starting worker $i"
    python3 -m p2pd_server_monitor.worker_process --log_path=worker_$i.log --py_p2pd_monitor &
done

wait