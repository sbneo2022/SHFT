## How to run 


1. Use virtual environment of `websocket_bot` project:

In `websocket_bot` project folder use:

```
source venv/bin/activate
```

For some operation systems (like linux) we have to make 

```
LD_LIBRARY_PATH=/usr/local/lib
export LD_LIBRARY_PATH
```

Actually in production we have this commands in `run.once.sh` script, which also help
to log all `stdout` to a file

### Entry file

```
python app.py
```

This command will run entry file **with empty** configuration. In most cases it will not work and we have to
construct configuration. We can use basic examples from `yaml` folder

```
python app.py --add yaml/arbitrage.yaml --add yaml/api.yaml --add yaml/capital.yaml
```

Best practice is to have: 
  
  - all API and Database settings in `api` file
  
  - financial settings (how much to bet) in `capital` file
  
  - Logic setting (what to run and how to operate) in `arbitrage` file
  
## Settings

- `cex` section: it could be dict for *single account mode* or list of dict for *multi account mode*

   It should have:
   
     - `key` and `secret` of CEX account
     
     - `address` used for CEX deposit for BEP2 network
     
     - `memo` used for CEX deposit for BEP2 network
     
- `dex` section:

     - `address` and `private_key` of DEX wallet
     
- `bepswap` section: its constant now. Also `thorswap` and `delphidigital` are support


- `influx` section:

     - `host`, `port`, `username`, `password` values to InfluxDb access
     
     - `database` where log will be written; `user` should have write access if that database exists, and 
     admin access is database is absent and have to be created
     
- `method` section: method of `Worker` class that will be activated. Also it will be base of measurement 
name for database log

- [optional] `prefix`: Prefix used for measurement name. Default is `bepswap`

- `threshold` percent (0.01 means 1%) of possible arbitrage ROC when bot trying to get arbitrage revenue
    
    If possible ROC less than threshold bot just exit. If possible ROC greater than threshold bot is 
    starting arbitrage procedure  
    
- `capital` Max amount of swap capital in USD. BNB amount will be calculated using current BNB-USD rate

- `scattering` Value most likely 0 < x < 0.2 (where 0.1 = 10%) indicated how do we randomize bet capital. This 
value used for increment and decrement: 0.1 means +/-10%

   *Note: currently we are looking for best capital from `capital` down to $500 and `scattering` is not used*


