# How to use Sandboxes 

## General notes

### How to create Virtual Environment

Usually you can create venv with command:

```shell script
python -m venv venv
```

or

```shell script
python3 -m venv venv
```

### How to activate Virtual Environment

```shell script
source venv venv
```
 
### How to install Libraries

First you have to activate venv, then:

```shell script
pip install -r requirements
```

## ATR Sandbox

```shell script
cd sandbox
python new_atr_sandbox.py
```

Actually this file running part (one event) of CLPATR bot
 