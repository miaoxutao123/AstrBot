"""Control Plane CRUD API for WebUI-managed adapter definitions."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope

router = APIRouter(prefix="/v1", tags=["managed-adapters"])


def _store(request: Request) -> Any:
    store = get_services(request).managed_adapters
    if store is None:
        raise RuntimeError("Managed Adapter Store is not configured")
    return store


async def _save_secrets(request: Request, adapter_id: str, config: dict[str, Any]) -> dict[str, Any]:
    secrets = get_services(request).managed_secrets
    if secrets is None:
        return config
    result = dict(config)
    for key, value in tuple(result.items()):
        if isinstance(value, dict) and value.get("clear") is True:
            await secrets.delete(adapter_id, key)
            result.pop(key)
        elif key in {"secret", "token", "app_secret"} and isinstance(value, str):
            result[key] = await secrets.set(adapter_id, key, value)
    return result


@router.get("/adapter-instances")
async def list_instances(
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    managed = _store(request).list()
    yaml_instances = [
        {
            "id": info.adapter_id,
            "type": info.adapter_type,
            "family": info.family,
            "state": info.state.value,
            "source": "yaml",
            "read_only": True,
        }
        for info in get_services(request).runtime.list_info()
        if info.adapter_id not in {item["id"] for item in managed}
    ]
    secrets = get_services(request).managed_secrets
    if secrets is not None:
        managed = [{**item, "config": secrets.public(item["config"])} for item in managed]
    return {"instances": [*yaml_instances, *managed]}


@router.post("/adapter-instances")
async def create_instance(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, Any]:
    config = await _save_secrets(request, str(body.get("id", "")), dict(body.get("config", {})))
    return dict(_store(request).put(
            str(body.get("id", "")),
            str(body.get("type", "")),
            bool(body.get("enabled", True)),
            config,
        ))


@router.patch("/adapter-instances/{adapter_id}")
async def patch_instance(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
    adapter_id: str,
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, Any]:
    changes = dict(body)
    if "config" in changes:
        changes["config"] = await _save_secrets(
            request, adapter_id, dict(changes["config"])
        )
    return dict(_store(request).patch(adapter_id, changes))


@router.get("/adapter-types")
async def adapter_types(
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    return {
        "adapter_types": [
            {"type": name, "name": name.replace("_", " ").title()}
            for name in get_services(request).runtime.adapter_types()
        ]
    }


@router.delete("/adapter-instances/{adapter_id}")
async def delete_instance(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
    adapter_id: str,
    request: Request,
) -> dict[str, str]:
    _store(request).delete(adapter_id)
    return {"status": "deleted"}
