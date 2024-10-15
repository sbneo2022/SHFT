from typing import Optional

from lib.constants import KEY
from lib.vault import AbstractVault, VAULT


class ConfigVault(AbstractVault):
    def __init__(self, config: Optional[dict] = None, **kwargs):
        super().__init__(config)
        self._exchange = self._config[KEY.EXCHANGE]

        exchange_section = self._config.get(self._exchange, None) or {}

        self._credentials = {
            VAULT.KEY: exchange_section.get(VAULT.KEY, None),
            VAULT.SECRET: exchange_section.get(VAULT.SECRET, None),
            VAULT.PASSPHRASE: str(exchange_section.get(VAULT.PASSPHRASE, None)),
            VAULT.PRIVATE_KEY: str(exchange_section.get(VAULT.PRIVATE_KEY, None)),
            VAULT.ADDRESS: str(exchange_section.get(VAULT.ADDRESS, None)),
        }

    def Get(self, key: str):
        return self._credentials.get(key, None)