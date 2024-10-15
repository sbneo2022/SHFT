# This example uses Python 2.7 and the python-request library.

from requests import Request, Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json
import os, path
import time
import tqdm

url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/info"
PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "../../../",
    "tools/pancake/data/pancake/reference.json",
)


def load_reference_file():
    with open(
        PATH,
        "r",
    ) as f:
        return json.load(f)


def get_tags(symbol):
    parameters = {"aux": "tags", "symbol": symbol}
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": "e136c91b-b4a6-4bbc-851d-809caf71faf4",
    }

    session = Session()
    session.headers.update(headers)

    response = session.get(url, params=parameters)
    try:
        data = json.loads(response.text)
        return data["data"][symbol]["tags"]
    except Exception as e:
        print(e, response.text)


def main():
    output = {}
    for key, value in tqdm.tqdm(load_reference_file().items()):
        time.sleep(5)

        value = dict(value)
        value["tags"] = get_tags(value["base_asset"])

        output[key] = value

    with open(PATH, "w") as fp:
        json.dump(output, fp, indent=2, sort_keys=True)


if __name__ == "__main__":
    # print(get_tags("MBOX"))
    main()
