import os
from abc import ABC, abstractmethod
from typing import Dict, Type
from anyio import Path

_STORAGES: Dict[str, Type["BaseStorage"]] = {}

def register_storage(cls: Type["BaseStorage"]) -> Type["BaseStorage"]:
    """
    Registry decorator that maps a storage class to its unique name identifier.

    This enables the factory to resolve and instantiate the correct storage 
    adapter based on external configuration strings without modifying the 
    core orchestration logic.
    """
    _STORAGES[cls.name] = cls
    return cls

def get_storage(name: str, **kwargs) -> "BaseStorage":
    """
    Factory function to retrieve a specific storage adapter instance.

    It looks up the requested name in the global registry and passes 
    any additional keyword arguments to the adapter's constructor.

    Raises:
        ValueError: If the requested storage name is not registered.
    """
    if name not in _STORAGES:
        raise ValueError(f"Unknown storage adapter: '{name}'")
    return _STORAGES[name](**kwargs)

class BaseStorage(ABC):
    """
    Abstract base class defining the contract for all persistent storage layers.

    Any implementation must provide asynchronous methods for basic file 
    operations to ensure non-blocking I/O across the application.
    """
    name: str

    @abstractmethod
    async def save(self, relative_path: str, data: bytes) -> str:
        """
        Persists raw bytes into the storage backend.

        Returns:
            A string representing the absolute URI or path to the stored resource.
        """
        pass

    @abstractmethod
    async def read(self, uri: str) -> bytes:
        """
        Retrieves the binary content of a file located at the given URI.
        """
        pass
        
    @abstractmethod
    async def delete(self, uri: str) -> bool:
        """
        Removes a file from the storage system.

        Returns:
            True if the operation succeeded, False otherwise.
        """
        pass

    @abstractmethod
    async def exists(self, uri: str) -> bool:
        """
        Determines if a resource currently exists at the specified URI.
        """
        pass

@register_storage
class LocalStorage(BaseStorage):
    """
    Storage adapter for the local host file system.

    It utilizes 'anyio' for asynchronous path operations, ensuring that 
    the event loop is not blocked during disk I/O.
    """
    name = "local"

    def __init__(self, base_path: str = "/tmp/papers"):
        self.base_path = Path(base_path)

    async def _ensure_dir(self, target_path: Path):
        """
        Recursively creates the parent directories for a given file path.
        """
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
        target = Path(uri)
        return await target.exists()