#!/bin/sh

mkdir -p logs

log_filename=logs/$(date "+%Y.%m.%d-%H:%M:%S.%N").log

until python "$@" >> $log_filename 2>&1; do
 echo "Restart..."
 sleep 10
done

