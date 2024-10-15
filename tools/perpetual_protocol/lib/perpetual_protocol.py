import json
import os
import sys
from decimal import Decimal
from pprint import pprint
from typing import Dict, Tuple, Any

from eth_typing import Address
from web3 import Web3, HTTPProvider, WebsocketProvider

import requests

sys.path.append(os.path.abspath('../../..'))
from tools.perpetual_protocol.lib.constants import KEY, EXCHANGE

METADATA_URL = 'https://metadata.perp.exchange/production.json'
NETWORK = 'xdai'

PP_BASE = 'USDC'
EXCHANGE_NAME = EXCHANGE.PERPETUAL_PROTOCOL

AMM_READER_ABI = '[{"type":"function","stateMutability":"view","outputs":[{"type":"tuple","name":"",' \
                 '"internalType":"struct AmmReader.AmmStates","components":[{"type":"uint256",' \
                 '"name":"quoteAssetReserve","internalType":"uint256"},{"type":"uint256",' \
                 '"name":"baseAssetReserve","internalType":"uint256"},{"type":"uint256",' \
                 '"name":"tradeLimitRatio","internalType":"uint256"},{"type":"uint256",' \
                 '"name":"fundingPeriod","internalType":"uint256"},{"type":"string",' \
                 '"name":"quoteAssetSymbol","internalType":"string"},{"type":"string",' \
                 '"name":"baseAssetSymbol","internalType":"string"},{"type":"bytes32",' \
                 '"name":"priceFeedKey","internalType":"bytes32"},{"type":"address",' \
                 '"name":"priceFeed","internalType":"address"}]}],"name":"getAmmStates",' \
                 '"inputs":[{"type":"address","name":"_amm","internalType":"address"}]}]'


class PerpetualProtocol:
    def __init__(self, config: dict):
        self._config = config

        self._node_http = self._config['perpetual_protocol']['http']
        self._metadata = self._get_metadata()

        self._amm_reader_address = self._get_amm_reader_address(self._metadata)
        self._products = self._get_products_and_addresses(self._metadata)

        self._w3 = Web3(HTTPProvider(self._node_http))
        # self._w3 = Web3(WebsocketProvider(self._node_http))

        self._amm_reader = self._w3.eth.contract(address=self._amm_reader_address, abi=AMM_READER_ABI)


    def _get_metadata(self) -> dict:
        r = requests.get(METADATA_URL)
        return r.json()

    def _get_amm_reader_address(self, metadata: dict) -> Address:
        for layer in metadata['layers'].values():
            if layer['network'] == NETWORK:
                address = layer['contracts']['AmmReader']['address']
                return Address(address)

    def _get_products_and_addresses(self, metadata: dict) -> Dict[str, str]:
        return_me = dict()
        for layer in metadata['layers'].values():
            if layer['network'] == NETWORK:
                for name, data in layer['contracts'].items():
                    if data['name'] == 'Amm':
                        return_me[name] = data['address']
        return return_me

    @staticmethod
    def _decode_tuple_using_abi(abi: str, name: str, tuple: Tuple) -> Dict[str, Any]:
        return_me = {}
        for item in json.loads(abi):
            if item['type'] == 'function' and item['name'] == name:
                for output in item['outputs']:
                    for field, value in zip(output['components'], tuple):
                        return_me[field['name']] = value
        return return_me

    def getProductsData(self) -> Dict[str, dict]:
        return_me = dict()
        for address in self._products.values():
            data = self._amm_reader.functions.getAmmStates(address).call()
            data = self._decode_tuple_using_abi(AMM_READER_ABI, 'getAmmStates', data)

            product = data['baseAssetSymbol'] + '-' + data['quoteAssetSymbol']

            return_me[product] = data

            baseAssetReserve = Decimal(return_me[product]['baseAssetReserve'])
            quoteAssetReserve = Decimal(return_me[product]['quoteAssetReserve'])

            return_me[product] = {
                KEY.EXCHANGE: EXCHANGE_NAME,
                KEY.BASE_DEPTH: baseAssetReserve,
                KEY.QUOTE_DEPTH: quoteAssetReserve,
                KEY.POOL_PRICE: quoteAssetReserve / baseAssetReserve
            }

        return return_me