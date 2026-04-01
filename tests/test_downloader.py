"""
Test suite for the asynchronous academic asset downloader module.

This suite provides comprehensive validation for the `_download_asset` function 
within the ingestion pipeline. It relies heavily on `httpx` mocking to simulate 
various real-world network conditions and academic publisher behaviors, ensuring 
the system remains resilient against bot-blocking mechanisms, invalid payloads, 
and network unreliability.
"""
import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock
from papers.backend.tasks import _download_asset

def create_mock_response(status_code: int, content: bytes, headers: dict, text: str = "") -> MagicMock:
    """
    Constructs a controlled mock of an httpx.Response object.
    """
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.headers = headers
    response.text = text
    return response

@pytest.fixture
def mock_httpx_client():
    """
    Overrides the httpx.AsyncClient context manager to intercept network calls.
    """
    with patch("papers.backend.tasks.httpx.AsyncClient") as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_instance
        yield mock_instance

@pytest.mark.anyio
async def test_direct_pdf_binary_hit(mock_httpx_client):
    """
    Validates successful extraction when the target URL directly returns a valid PDF binary.
    """
    target_url = "https://example.com/paper.pdf"
    mock_response = create_mock_response(
        status_code=200,
        content=b"%PDF-1.5 \nBinary Data",
        headers={"Content-Type": "application/pdf"}
    )
    mock_httpx_client.get.return_value = mock_response

    result, mime = await _download_asset(target_url, "application/pdf")

    assert result == b"%PDF-1.5 \nBinary Data"
    assert mime == "application/pdf"
    mock_httpx_client.get.assert_called_once()

@pytest.mark.anyio
async def test_invalid_pdf_payload_rejection(mock_httpx_client):
    """
    Ensures the pipeline rejects payloads that report HTTP 200 OK but lack PDF magic bytes.
    """
    target_url = "https://example.com/fake.pdf"
    mock_response = create_mock_response(
        status_code=200,
        content=b"<!DOCTYPE html><html>Captcha Page</html>",
        headers={"Content-Type": "application/pdf"}
    )
    mock_httpx_client.get.return_value = mock_response

    with pytest.raises(ValueError, match="Asset acquisition failed"):
        await _download_asset(target_url, "application/pdf")

@pytest.mark.anyio
async def test_academic_metadata_heuristic_absolute_url(mock_httpx_client):
    """
    Validates the HTML parsing fallback when landing on an academic repository page.
    """
    target_url = "https://scholar.publisher.com/article/123"
    real_pdf_url = "https://scholar.publisher.com/download/123.pdf"
    
    html_content = f'''
    <html>
        <head>
            <meta name="citation_pdf_url" content="{real_pdf_url}">
        </head>
        <body>Paywall</body>
    </html>
    '''
    
    html_response = create_mock_response(
        status_code=200,
        content=html_content.encode("utf-8"),
        headers={"Content-Type": "text/html"},
        text=html_content
    )
    
    pdf_response = create_mock_response(
        status_code=200,
        content=b"%PDF-1.4 Valid Document",
        headers={"Content-Type": "application/pdf"}
    )

    mock_httpx_client.get.side_effect = [html_response, pdf_response]

    result, mime = await _download_asset(target_url, "application/pdf")

    assert result == b"%PDF-1.4 Valid Document"
    assert mime == "application/pdf"
    assert mock_httpx_client.get.call_count == 2
    mock_httpx_client.get.assert_any_call(target_url, timeout=45.0)
    mock_httpx_client.get.assert_any_call(real_pdf_url, timeout=45.0)

@pytest.mark.anyio
async def test_academic_metadata_heuristic_relative_url(mock_httpx_client):
    """
    Validates relative URL resolution during HTML metadata extraction.
    """
    target_url = "https://repository.edu/view/456"
    relative_path = "/assets/456.pdf"
    expected_absolute_url = "https://repository.edu/assets/456.pdf"
    
    html_content = f'<meta property="citation_pdf_url" content="{relative_path}">'
    
    html_response = create_mock_response(
        status_code=200,
        content=html_content.encode("utf-8"),
        headers={"Content-Type": "text/html"},
        text=html_content
    )
    
    pdf_response = create_mock_response(
        status_code=200,
        content=b"%PDF-1.4 Valid Relative Document",
        headers={"Content-Type": "application/pdf"}
    )

    mock_httpx_client.get.side_effect = [html_response, pdf_response]

    result, mime = await _download_asset(target_url, "application/pdf")

    assert result == b"%PDF-1.4 Valid Relative Document"
    assert mime == "application/pdf"
    mock_httpx_client.get.assert_any_call(expected_absolute_url, timeout=45.0)

@pytest.mark.anyio
async def test_network_failure_handling(mock_httpx_client):
    """
    Ensures network-level exceptions trigger the correct fallback escalation.
    """
    target_url = "https://example.com/timeout.pdf"
    mock_httpx_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")

    with pytest.raises(ValueError, match="Asset acquisition failed"):
        await _download_asset(target_url, "application/pdf")

@pytest.mark.anyio
async def test_http_error_status_handling(mock_httpx_client):
    """
    Verifies that non-200 HTTP responses trigger the correct fallback escalation.
    """
    target_url = "https://example.com/forbidden.pdf"
    mock_response = create_mock_response(
        status_code=403,
        content=b"Forbidden",
        headers={"Content-Type": "text/html"}
    )
    mock_httpx_client.get.return_value = mock_response

    with pytest.raises(ValueError, match="Asset acquisition failed"):
        await _download_asset(target_url, "application/pdf")