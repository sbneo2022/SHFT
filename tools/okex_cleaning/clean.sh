#!/bin/bash

mkdir -p logs

log_filename=logs/$(date "+%Y.%m.%d-%H:%M:%S.%N").log

source ../../venv/bin/activate

python clean.py $1 $2 $3 $4 2>&1 | tee -a $log_filename

deactivate
