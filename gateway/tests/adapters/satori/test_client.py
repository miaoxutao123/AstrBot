"""Production Satori client lifecycle classification tests."""

from gateway.adapters.satori.client import AiohttpSatoriClient
from gateway.adapters.satori.config import SatoriConfig


class Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class HandshakeFailure(Exception):
    def __init__(self, status_code: int) -> None:
        self.response = Response(status_code)


def test_websocket_authentication_rejection_classification() -> None:
    client = AiohttpSatoriClient(SatoriConfig.from_mapping({}), None)

    assert client._is_authentication_rejection(HandshakeFailure(401))
    assert client._is_authentication_rejection(HandshakeFailure(403))
    assert not client._is_authentication_rejection(HandshakeFailure(500))
    assert not client._is_authentication_rejection(ConnectionError())
