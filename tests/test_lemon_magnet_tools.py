import os
import sys
import urllib.parse

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "plugins")),
)

from astrbot_plugin_lemon import magnet_tools


def test_parse_speed_to_bytes():
    assert magnet_tools._parse_speed_to_bytes("0B") == 0.0
    assert abs(magnet_tools._parse_speed_to_bytes("1KiB") - 1024.0) < 1e-6
    assert abs(magnet_tools._parse_speed_to_bytes("1.5MiB") - (1.5 * 1024 * 1024)) < 1e-6
    assert magnet_tools._parse_speed_to_bytes("n/a") == 0.0


def test_classify_health():
    assert magnet_tools._classify_health(0, 0)[0].startswith("🔴")
    assert magnet_tools._classify_health(3, 0)[0].startswith("🟠")
    assert magnet_tools._classify_health(2, 64 * 1024)[0].startswith("🟡")
    assert magnet_tools._classify_health(5, 512 * 1024)[0].startswith("🟢")


def test_cache_key_uses_infohash_when_available():
    magnet = "magnet:?xt=urn:btih:ABCDEF1234567890&dn=test"
    key = magnet_tools._cache_key(magnet, timeout=30)
    assert key.startswith("abcdef1234567890:")


def test_cache_key_fallback_is_stable():
    magnet = "magnet:?dn=test&tr=udp://tracker.example:6969/announce"
    k1 = magnet_tools._cache_key(magnet, timeout=30)
    k2 = magnet_tools._cache_key(magnet, timeout=30)
    assert k1 == k2
    assert k1.startswith("magnet:")


def test_check_magnet_health_rejects_invalid_magnet():
    msg = magnet_tools.check_magnet_health_logic("https://example.com/not_magnet", timeout=10)
    assert "无效磁力链接" in msg


def test_augment_magnet_with_public_trackers_adds_trackers():
    base = "magnet:?xt=urn:btih:ABCDEF1234567890&dn=test"
    updated, added = magnet_tools.augment_magnet_with_public_trackers(base)
    parsed = urllib.parse.urlsplit(updated)
    query = urllib.parse.parse_qs(parsed.query)
    assert updated.startswith("magnet:?")
    assert "tr" in query
    assert len(query["tr"]) >= len(magnet_tools._PUBLIC_TRACKERS)
    assert added > 0


def test_augment_magnet_with_public_trackers_dedupes_existing():
    existing = magnet_tools._PUBLIC_TRACKERS[0]
    base = (
        "magnet:?xt=urn:btih:ABCDEF1234567890&dn=test&tr="
        + urllib.parse.quote(existing, safe="")
    )
    updated, added = magnet_tools.augment_magnet_with_public_trackers(base)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(updated).query)
    tr_values = query.get("tr", [])
    assert tr_values.count(existing) == 1
    assert added == len(magnet_tools._PUBLIC_TRACKERS) - 1
