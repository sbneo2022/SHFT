## How to install

This arbitrage bot is a tool of `websocket_bot` framework. In order to run we have ot install all libraries 
from `websocket_bot` project also with some custom steps

1. Install basic libraries:

    ```
    pip install -r requirements.txt
    ```

2. Install `libsecp256k1` library on a target operation system

3. Install `python_binance_chain`

    - For python 3.8.x:
    
        ```
        pip install python_binance_chain
        ```
    
    - For python 3.9.x:
    
        ```
        pip install --use-deprecated=legacy-resolver python_binance_chain
        ```

4. Install 'libsecp256k1' library for python

```
INCLUDE_DIR=/usr/local/Cellar/libsecp256k1/0.1/include LIB_DIR=/usr/local/Cellar/libsecp256k1/0.1/lib pip install --no-binary :all: secp256k1
```

