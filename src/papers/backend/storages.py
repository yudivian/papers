"""
Extensible storage layer for the Papers AI Engine.

This module provides the abstract interfaces and registry patterns necessary 
to decouple physical file persistence from the application's business logic. 
By delegating all file system operations (saving, deleting, verifying, and serving) 
to registered adapters, the system seamlessly supports local disk storage, 
cloud buckets (e.g., AWS S3), and distributed file systems.
"""
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Type
from anyio import Path
from fastapi.responses import Response, FileResponse

_STORAGES: Dict[str, Type["BaseStorage"]] = {}

def register_storage(cls: Type["BaseStorage"]) -> Type["BaseStorage"]:
    """
    Registry decorator that maps a storage class to its unique name identifier.
    """
    _STORAGES[cls.name] = cls
    return cls

def get_storage(name: str, **kwargs) -> "BaseStorage":
    """
    Factory function to retrieve a specific storage adapter instance.
    """
    if name not in _STORAGES:
        raise ValueError(f"Unknown storage adapter: '{name}'")
    return _STORAGES[name](**kwargs)

class BaseStorage(ABC):
    """
    Abstract base class defining the contract for all persistent storage layers.
    """
    name: str

    @abstractmethod
    async def save(self, relative_path: str, data: bytes) -> str:
        pass

    @abstractmethod
    async def read(self, uri: str) -> bytes:
        pass

    @abstractmethod
    async def delete(self, uri: str) -> bool:
        pass

    @abstractmethod
    async def exists(self, uri: str) -> bool:
        pass

    @abstractmethod
    async def get_size(self, uri: str) -> int:
        pass

    @abstractmethod
    async def get_modified_time(self, uri: str) -> datetime:
        pass

    @abstractmethod
    async def serve(self, uri: str, media_type: str, filename: str) -> Response:
        """
        Constructs an appropriate HTTP response for serving the file to the client.
        """
        pass

@register_storage
class LocalStorage(BaseStorage):
    """
    Storage adapter for the local host file system using asynchronous I/O.
    """
    name = "local"

    def __init__(self, base_path: str = "/tmp/papers"):
        self.base_path = Path(base_path)

    async def _ensure_dir(self, target_path: Path):
        await target_path.parent.mkdir(parents=True, exist_ok=True)

    async def save(self, relative_path: str, data: bytes) -> str:
        parts = Path(relative_path).parts
        safe_parts = [p for p in parts if p not in (os.sep, "..", ".", "/")]
        full_path = self.base_path.joinpath(*safe_parts)
        
        await self._ensure_dir(full_path)
        await full_path.write_bytes(data)
        
        return str(full_path)

    async def read(self, uri: str) -> bytes:
        target = Path(uri)
        if not await target.exists():
            raise FileNotFoundError(f"File not found at URI: {uri}")
        return await target.read_bytes()

    async def delete(self, uri: str) -> bool:
        target = Path(uri)
        if await target.exists():
            await target.unlink()
            return True
        return False

    async def exists(self, uri: str) -> bool:
        return await Path(uri).exists()

    async def get_size(self, uri: str) -> int:
        stat = await Path(uri).stat()
        return stat.st_size

    async def get_modified_time(self, uri: str) -> datetime:
        stat = await Path(uri).stat()
        return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    async def serve(self, uri: str, media_type: str, filename: str) -> Response:
        if not await self.exists(uri):
            raise FileNotFoundError(f"File not found at URI: {uri}")
        return FileResponse(
            path=uri,
            media_type=media_type,
            filename=filename
        )