from unittest.mock import Mock

import jwt
import pytest

from astrbot.dashboard.services.plugin_page_service import PluginPageService


@pytest.mark.parametrize(
    ("settings", "expected_minutes"),
    [
        ({}, 5),
        ({"plugin_page_token_ttl_minutes": 1}, 1),
        ({"plugin_page_token_ttl_minutes": 60}, 60),
        ({"plugin_page_token_ttl_minutes": 0}, 5),
        ({"plugin_page_token_ttl_minutes": 61}, 5),
        ({"plugin_page_token_ttl_minutes": True}, 5),
        ({"plugin_page_token_ttl_minutes": "10"}, 5),
    ],
)
def test_plugin_page_token_lifetime(settings, expected_minutes):
    secret = "test-plugin-page-signing-secret-32-bytes"
    service = PluginPageService(Mock(), config={"dashboard": settings})
    token = service.issue_plugin_page_asset_token(
        plugin_name="example",
        view_name="settings",
        username="alice",
        locale="en-US",
        jwt_secret=secret,
    )
    claims = jwt.decode(token, secret, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == expected_minutes * 60
