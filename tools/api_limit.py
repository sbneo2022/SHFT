import requests

URL = 'https://fapi.binance.com'

def get_api_limit(url: str) -> int:
    while True:
        r = requests.get(url + '/fapi/v1/allForceOrders')
        print(r.headers['X-MBX-USED-WEIGHT-1M'], '   ', r.reason)
        if r.status_code != 200:
            return int(r.headers['X-MBX-USED-WEIGHT-1M'])

if __name__ == '__main__':
    limit = get_api_limit(URL)

    print(f'API limit for {URL} = {limit}')