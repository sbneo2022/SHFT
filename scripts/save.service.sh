#!/bin/bash

prefix="save"

symbols=$(cat symbols.txt)
exchanges=("BINANCE.FUTURES" "OKEX.PERP" "HUOBI.SWAP")

if [[ "$1" = "start" ]]; then
  cd ..
  for symbol in $symbols
  do
    for exchange in ${exchanges[*]}
    do
      name="$prefix-$symbol~$exchange"
      screen -dmS $name bash -c "source ./venv/bin/activate; ./run.forever.sh service.py $2 $3 $4 $5 --add '$(jo symbol=$symbol exchange=$exchange)'"
      echo "Running $item in '$name' screen"
      sleep 0.25
    done
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
  echo "usage: $0 start|stop"
fi
