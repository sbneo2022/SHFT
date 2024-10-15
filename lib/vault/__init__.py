from abc import ABC, abstractmethod
from typing import Optional

class VAULT:
    KEY = 'key'
    SECRET = 'secret'
    PASSPHRASE = 'passphrase'
    PRIVATE_KEY = 'private_key'
    ADDRESS = 'address'

class AbstractVault(ABC):
    def __init__(self, config: Optional[dict] = None, **kwargs):
        self._config = config or {}

    @abstractmethod
    def Get(self, key: str):
        pass