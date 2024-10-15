#!/bin/bash

name="telegram"

if [[ "$1" = "start" ]]; then
      screen -dmS $name bash -c "source ./venv/bin/activate; pip install -r requirements.txt; ./run.forever.sh app.py"
      echo "Running service '$name' screen"

elif [[ $1 = "stop" ]]; then
    echo "Sending ^C Signal to '$name' screen"
    screen -XS $name stuff "^C"

else
  echo "usage: $0 start|stop"
fi
