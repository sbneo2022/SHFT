#!/bin/bash

prefix="dev"

usage="Usage: $0 start|stop [path with mask] [arg_1] ... [arg_4]"

if [[ "$1" = "start" ]]; then
  cd ..
  for item in $2
    do
      if test -f "$item"; then
        name="$prefix-$(sed 's:/:-:g' <<<"$item")"
        screen -dmS $name bash -c "source ./venv/bin/activate; ./run.forever.sh service.py $3 $4 $5 $6 $7 $8 --add $item"
        echo "Running $item in '$name' screen"
      else
        echo -e "'$item' YAML file not found. \n$usage"
      fi
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
