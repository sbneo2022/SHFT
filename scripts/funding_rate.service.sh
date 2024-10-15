#!/bin/bash

prefix="funding_rate"

usage="Usage: $0 start|stop [arg_1] ... [arg_4]"

products=$(source ../venv/bin/activate; python ../tools/funding_rate/funding_rate_report.py -n 5)

if [[ "$1" = "start" ]]; then
  cd ..
  for item in $products
    do
      name="$prefix-$(sed 's:/:-:g' <<<"$item")"
      screen -dmS $name bash -c "source ./venv/bin/activate; ./run.forever.sh service.py $2 $3 $4 $5 $6 $7 --add '$(jo symbol=$item hedge=$(jo symbol=$item))'"
      echo "Running $item in '$name' screen"
    done

elif [[ $1 = "stop" ]]; then
  for i in $(screen -ls | grep $prefix | awk '{print $1}')
  do
    echo "Sending ^C Signal to '$i' screen"
    screen -XS $i stuff "^C"
  done
  sleep 3
  for i in $(screen -ls | grep $prefix | awk '{print $1}')
  do
    echo "Killing '$i' screen"
    screen -XS $i quit
  done

else
  echo $usage
fi
