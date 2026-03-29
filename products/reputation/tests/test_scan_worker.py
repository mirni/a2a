"""Tests for the ScanWorker."""

from __future__ import annotations

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from products.reputation.src.scan_worker import (
    HEADER_WEIGHT,
    SECURITY_HEADERS,
    ScanWorker,
    analyze_security_headers,
    check_auth_required,
    check_tls_from_url,
)


class TestAnalyzeSecurityHeaders:
    def test_no_security_headers(self):
        headers = httpx.Headers({})
        result = analyze_security_headers(headers)
        assert result.has_hsts is False
        assert result.has_csp is False
        assert result.has_x_frame_options is False
        assert result.has_x_content_type_options is False
        assert result.has_referrer_policy is False
        assert result.header_score == 0.0

    def test_all_security_headers(self):
        headers = httpx.Headers(
            {
                "strict-transport-security": "max-age=31536000",
                "content-security-policy": "default-src 'self'",
                "x-frame-options": "DENY",
                "x-content-type-options": "nosniff",
                "referrer-policy": "no-referrer",
            }
        )
        result = analyze_security_headers(headers)
        assert result.has_hsts is True
        assert result.has_csp is True
        assert result.has_x_frame_options is True
        assert result.has_x_content_type_options is True
        assert result.has_referrer_policy is True
        assert result.header_score == 100.0

    def test_partial_headers_hsts_only(self):
        headers = httpx.Headers(
            {
                "strict-transport-security": "max-age=31536000",
            }
        )
        result = analyze_security_headers(headers)
        assert result.has_hsts is True
        assert result.has_csp is False
        assert result.header_score == pytest.approx(HEADER_WEIGHT, abs=0.01)

    def test_partial_headers_two(self):
        headers = httpx.Headers(
            {
                "strict-transport-security": "max-age=31536000",
                "x-frame-options": "SAMEORIGIN",
            }
        )
        result = analyze_security_headers(headers)
        assert result.has_hsts is True
        assert result.has_x_frame_options is True
        assert result.header_score == pytest.approx(2 * HEADER_WEIGHT, abs=0.01)

    def test_unrelated_headers_ignored(self):
        headers = httpx.Headers(
            {
                "content-type": "text/html",
                "server": "nginx",
            }
        )
        result = analyze_security_headers(headers)
        assert result.header_score == 0.0

    def test_header_weight_sums_to_100(self):
        assert HEADER_WEIGHT * len(SECURITY_HEADERS) == pytest.approx(100.0, abs=0.01)


class TestCheckTLSFromURL:
    def test_https_url(self):
        info = check_tls_from_url("https://example.com")
        assert info.enabled is True
        assert info.valid is True

    def test_http_url(self):
        info = check_tls_from_url("http://example.com")
        assert info.enabled is False
        assert info.valid is False

    def test_https_uppercase(self):
        info = check_tls_from_url("HTTPS://EXAMPLE.COM")
        assert info.enabled is True
        assert info.valid is True

    def test_http_with_port(self):
        info = check_tls_from_url("http://localhost:8080")
        assert info.enabled is False

    def test_https_with_path(self):
        info = check_tls_from_url("https://example.com/health")
        assert info.enabled is True


class TestCheckAuthRequired:
    def test_401_response(self):
        response = MagicMock()
        response.status_code = 401
        response.headers = httpx.Headers({})
        assert check_auth_required(response) is True

    def test_403_response(self):
        response = MagicMock()
        response.status_code = 403
        response.headers = httpx.Headers({})
        assert check_auth_required(response) is True

    def test_200_response(self):
        response = MagicMock()
        response.status_code = 200
        response.headers = httpx.Headers({})
        assert check_auth_required(response) is False

    def test_www_authenticate_header(self):
        response = MagicMock()
        response.status_code = 200
        response.headers = httpx.Headers({"www-authenticate": "Bearer"})
        assert check_auth_required(response) is True

    def test_500_without_auth(self):
        response = MagicMock()
        response.status_code = 500
        response.headers = httpx.Headers({})
        assert check_auth_required(response) is False


class TestScanWorkerScan:
    @pytest.mark.asyncio
    async def test_scan_https_with_headers(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers(
            {
                "strict-transport-security": "max-age=31536000",
                "content-security-policy": "default-src 'self'",
                "x-frame-options": "DENY",
            }
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        result = await worker.scan("svc-1", "https://example.com")

        assert result.server_id == "svc-1"
        assert result.tls_info.enabled is True
        assert result.tls_info.valid is True
        assert result.security_headers.has_hsts is True
        assert result.security_headers.has_csp is True
        assert result.security_headers.has_x_frame_options is True
        mock_trust_storage.store_security_scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_http_no_tls(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers({})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        result = await worker.scan("svc-1", "http://example.com")

        assert result.tls_info.enabled is False
        assert result.tls_info.valid is False

    @pytest.mark.asyncio
    async def test_scan_401_auth_required(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = httpx.Headers({"www-authenticate": "Bearer"})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        result = await worker.scan("svc-1", "https://example.com")

        assert result.auth_required is True

    @pytest.mark.asyncio
    async def test_scan_stores_trust_security_scan(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers(
            {
                "strict-transport-security": "max-age=31536000",
            }
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        await worker.scan("svc-1", "https://example.com")

        mock_trust_storage.store_security_scan.assert_called_once()
        stored = mock_trust_storage.store_security_scan.call_args[0][0]
        assert stored.server_id == "svc-1"
        assert stored.tls_enabled is True

    @pytest.mark.asyncio
    async def test_scan_connection_error(self, mock_trust_storage):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        result = await worker.scan("svc-1", "http://example.com")

        assert result.server_id == "svc-1"
        assert result.security_headers.header_score == 0.0

    @pytest.mark.asyncio
    async def test_scan_ssl_error(self, mock_trust_storage):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=ssl.SSLError("cert failed"))

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        result = await worker.scan("svc-1", "https://example.com")

        assert result.tls_info.enabled is True
        assert result.tls_info.valid is False

    @pytest.mark.asyncio
    async def test_scan_creates_client_if_none(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers({})

        with patch("products.reputation.src.scan_worker.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.aclose = AsyncMock()
            MockClient.return_value = mock_instance

            worker = ScanWorker(trust_storage=mock_trust_storage, timeout=5.0)
            result = await worker.scan("svc-1", "http://example.com")

            assert result.server_id == "svc-1"
            mock_instance.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_all_headers_perfect_score(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers(
            {
                "strict-transport-security": "max-age=31536000",
                "content-security-policy": "default-src 'self'",
                "x-frame-options": "DENY",
                "x-content-type-options": "nosniff",
                "referrer-policy": "no-referrer",
            }
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        result = await worker.scan("svc-1", "https://example.com")

        assert result.security_headers.header_score == 100.0
        assert result.input_validation_score == 100.0


class TestScanWorkerBatch:
    @pytest.mark.asyncio
    async def test_scan_batch(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers({})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ScanWorker(trust_storage=mock_trust_storage, client=mock_client)
        results = await worker.scan_batch(
            [
                ("svc-1", "https://a.com"),
                ("svc-2", "https://b.com"),
            ]
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_scan_batch_empty(self, mock_trust_storage):
        worker = ScanWorker(trust_storage=mock_trust_storage)
        results = await worker.scan_batch([])
        assert results == []
