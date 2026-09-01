"""Protect Core, API, and adapter package dependency boundaries."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).parents[2] / "gateway"


def imported_modules(root: Path) -> set[str]:
    """Collect imports from Python files below one package directory.

    Args:
        root: Package directory to inspect.

    Returns:
        Absolute module names present in import statements.
    """
    modules: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
    return modules


def test_core_does_not_import_profiles_api_or_adapter_sdks() -> None:
    modules = imported_modules(PACKAGE / "core")

    assert not any(name.startswith("gateway.profiles") for name in modules)
    assert not any(name.startswith("gateway.api") for name in modules)
    assert not any(name.startswith("gateway.adapters") for name in modules)
    assert "aiocqhttp" not in modules
    assert "aiohttp" not in modules
    assert not any(name == "Crypto" or name.startswith("Crypto.") for name in modules)
    assert "fastapi" not in modules


def test_api_does_not_import_onebot_or_its_sdks() -> None:
    modules = imported_modules(PACKAGE / "api")

    assert not any(name.startswith("gateway.adapters") for name in modules)
    assert "aiocqhttp" not in modules
    assert "aiohttp" not in modules


def test_onebot_does_not_import_astrbot_agent_runtime() -> None:
    modules = imported_modules(PACKAGE / "adapters" / "onebot")

    assert not any(name == "astrbot" or name.startswith("astrbot.") for name in modules)


def test_telegram_does_not_import_astrbot_agent_runtime() -> None:
    modules = imported_modules(PACKAGE / "adapters" / "telegram")

    assert not any(name == "astrbot" or name.startswith("astrbot.") for name in modules)


def test_weixin_does_not_import_astrbot_agent_runtime() -> None:
    modules = imported_modules(PACKAGE / "adapters" / "weixin")

    assert not any(name == "astrbot" or name.startswith("astrbot.") for name in modules)


def test_satori_does_not_import_astrbot_agent_runtime() -> None:
    modules = imported_modules(PACKAGE / "adapters" / "satori")

    assert not any(name == "astrbot" or name.startswith("astrbot.") for name in modules)


def test_qq_official_is_independent_from_astrbot_and_onebot() -> None:
    modules = imported_modules(PACKAGE / "adapters" / "qq_official")

    assert not any(name == "astrbot" or name.startswith("astrbot.") for name in modules)
    assert not any(name.startswith("gateway.adapters.onebot") for name in modules)
