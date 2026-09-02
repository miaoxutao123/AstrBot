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


def _public_instance(request: Request, instance: dict[str, Any]) -> dict[str, Any]:
    secrets = get_services(request).managed_secrets
    if secrets is None:
        return instance
    return {**instance, "config": secrets.public(instance["config"])}


async def _save_secrets(
    request: Request, adapter_id: str, config: dict[str, Any]
) -> dict[str, Any]:
    secrets = get_services(request).managed_secrets
    if secrets is None:
        return config
    result = dict(config)
    for key, value in tuple(result.items()):
        if (
            key in {"secret", "token", "app_secret"}
            and isinstance(value, dict)
            and value.get("clear") is True
        ):
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
        managed = [
            {**item, "config": secrets.public(item["config"])} for item in managed
        ]
    return {"instances": [*yaml_instances, *managed]}


@router.get("/adapter-instances/{adapter_id}")
async def get_instance(
    adapter_id: str,
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    managed = next(
        (item for item in _store(request).list() if item["id"] == adapter_id), None
    )
    if managed is not None:
        secrets = get_services(request).managed_secrets
        return {
            **managed,
            "config": secrets.public(managed["config"])
            if secrets
            else managed["config"],
        }
    info = get_services(request).runtime.info(adapter_id)
    return {
        "id": info.adapter_id,
        "type": info.adapter_type,
        "family": info.family,
        "state": info.state.value,
        "source": "yaml",
        "read_only": True,
    }


@router.post("/adapter-instances")
async def create_instance(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, Any]:
    adapter_id = str(body.get("id", ""))
    adapter_type = str(body.get("type", ""))
    if _store(request).get(adapter_id) is not None:
        raise ValueError("managed adapter id already exists; use PATCH to update it")
    if not get_services(request).runtime.supports_adapter_type(adapter_type):
        raise ValueError("adapter type is not available")
    config = await _save_secrets(request, adapter_id, dict(body.get("config", {})))
    instance = dict(
        _store(request).put(
            adapter_id,
            adapter_type,
            bool(body.get("enabled", True)),
            config,
        )
    )
    if instance["enabled"]:
        secrets = get_services(request).managed_secrets
        runtime_config = instance["config"]
        if secrets is not None:
            await secrets.populate_cache(
                [instance["config"]], request.app.state.managed_secret_values
            )
            runtime_config = secrets.runtime_config(runtime_config)
        await get_services(request).runtime.add_adapter(
            instance["id"], instance["type"], runtime_config
        )
    return _public_instance(request, instance)


@router.patch("/adapter-instances/{adapter_id}")
async def patch_instance(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
    adapter_id: str,
    request: Request,
    body: dict[str, Any] = Body(),
) -> dict[str, Any]:
    changes = dict(body)
    if "config" in changes:
        current = next(
            (item for item in _store(request).list() if item["id"] == adapter_id),
            None,
        )
        if current is None:
            raise ValueError("managed adapter was not found")
        # A PATCH is deliberately partial: absent secret fields retain their
        # existing opaque reference, while an explicit {"clear": true}
        # removes the reference and its backing secret.
        merged_config = {**current["config"], **dict(changes["config"])}
        changes["config"] = await _save_secrets(request, adapter_id, merged_config)
    instance = dict(_store(request).patch(adapter_id, changes))
    runtime = get_services(request).runtime
    try:
        await runtime.remove_adapter(adapter_id)
    except Exception:
        pass
    if instance["enabled"]:
        secrets = get_services(request).managed_secrets
        runtime_config = instance["config"]
        if secrets is not None:
            await secrets.populate_cache(
                [instance["config"]], request.app.state.managed_secret_values
            )
            runtime_config = secrets.runtime_config(runtime_config)
        await runtime.add_adapter(instance["id"], instance["type"], runtime_config)
    return _public_instance(request, instance)


@router.get("/adapter-types")
async def adapter_types(
    request: Request,
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:read"))],
) -> dict[str, Any]:
    return {
        "adapter_types": get_services(request).adapter_types.list(
            get_services(request).runtime.adapter_types()
        )
    }


@router.delete("/adapter-instances/{adapter_id}")
async def delete_instance(
    _principal: Annotated[ApiPrincipal, Depends(require_scope("adapters:manage"))],
    adapter_id: str,
    request: Request,
) -> dict[str, str]:
    try:
        await get_services(request).runtime.remove_adapter(adapter_id)
    except Exception:
        pass
    _store(request).delete(adapter_id)
    return {"status": "deleted"}
