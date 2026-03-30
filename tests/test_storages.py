import pytest
import os
import shutil
import tempfile
from anyio import Path
from papers.backend.storages import get_storage, LocalStorage

@pytest.fixture
def anyio_backend():
    """
    Configuration for anyio to use the asyncio backend during test execution.
    """
    return "asyncio"

@pytest.fixture
def temp_storage_dir():
    """
    Creates a temporary directory for file system operations and ensures 
    cleanup after the test suite completes.
    """
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path)

def test_storage_registry_resolution():
    """
    Validates that the storage factory correctly identifies and instantiates 
    the requested storage adapter by its registered string name.
    """
    storage = get_storage("local", base_path="/tmp")
    assert isinstance(storage, LocalStorage)
    assert storage.name == "local"

def test_storage_registry_failure_on_invalid_key():
    """
    Ensures that the factory raises a ValueError when an unregistered 
    storage identifier is requested.
    """
    with pytest.raises(ValueError):
        get_storage("non_existent_adapter")

@pytest.mark.anyio
async def test_local_storage_lifecycle(temp_storage_dir):
    """
    Verifies the complete lifecycle of a file within the local storage adapter, 
    including directory creation, data persistence, integrity during retrieval, 
    and successful deletion.
    """
    storage = get_storage("local", base_path=temp_storage_dir)
    filename = "subfolder/test_document.pdf"
    content = b"%PDF-1.4 test content"

    uri = await storage.save(filename, content)
    
    assert os.path.isabs(uri)
    assert temp_storage_dir in uri
    assert await storage.exists(uri)
    
    retrieved_data = await storage.read(uri)
    assert retrieved_data == content
    
    delete_success = await storage.delete(uri)
    assert delete_success is True
    assert await storage.exists(uri) is False

@pytest.mark.anyio
async def test_local_storage_security_traversal(temp_storage_dir):
    """
    Validates that the storage adapter prevents directory traversal attacks 
    by stripping leading slashes and forcing the resolution of relative 
    paths within the defined base directory.
    """
    storage = get_storage("local", base_path=temp_storage_dir)
    malicious_path = "/../../etc/passwd"
    content = b"malicious data"

    uri = await storage.save(malicious_path, content)
    
    assert temp_storage_dir in uri
    assert "etc/passwd" in uri
    assert not uri.startswith("/etc/passwd")

@pytest.mark.anyio
async def test_local_storage_read_non_existent_file(temp_storage_dir):
    """
    Confirms that attempting to read a non-existent URI results in a 
    standard FileNotFoundError.
    """
    storage = get_storage("local", base_path=temp_storage_dir)
    invalid_uri = os.path.join(temp_storage_dir, "ghost.pdf")
    
    with pytest.raises(FileNotFoundError):
        await storage.read(invalid_uri)