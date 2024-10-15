import os
from typing import Optional

from lib.vault import AbstractVault, VAULT


class EnvVault(AbstractVault):
    def __init__(self, config: Optional[dict] = None, **kwargs):
        super().__init__(config)

        self._credentials = {
            VAULT.KEY: os.getenv(VAULT.KEY.upper(), default=None),
            VAULT.SECRET: os.getenv(VAULT.SECRET.upper(), default=None),
            VAULT.PASSPHRASE: str(os.getenv(VAULT.PASSPHRASE.upper(), default=None)),
            VAULT.PRIVATE_KEY: str(os.getenv(VAULT.PRIVATE_KEY.upper(), default=None)),
            VAULT.ADDRESS: str(os.getenv(VAULT.ADDRESS.upper(), default=None)),
        }

    def Get(self, key: str):
        return self._credentials.get(key, None)