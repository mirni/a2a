"""Tests for the ProbeWorker."""

from __future__ import annotations

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from products.reputation.src.models import ProbeErrorType
from products.reputation.src.probe_worker import ProbeWorker, classify_error


class TestClassifyError:
    def test_success_no_exception(self):
        assert classify_error(None, 200) == ProbeErrorType.SUCCESS

    def test_success_301(self):
        assert classify_error(None, 301) == ProbeErrorType.SUCCESS

    def test_http_4xx(self):
        assert classify_error(None, 404) == ProbeErrorType.HTTP_4XX

    def test_http_400(self):
        assert classify_error(None, 400) == ProbeErrorType.HTTP_4XX

    def test_http_499(self):
        assert classify_error(None, 499) == ProbeErrorType.HTTP_4XX

    def test_http_5xx(self):
        assert classify_error(None, 500) == ProbeErrorType.HTTP_5XX

    def test_http_503(self):
        assert classify_error(None, 503) == ProbeErrorType.HTTP_5XX

    def test_no_exception_no_status(self):
        assert classify_error(None, None) == ProbeErrorType.SUCCESS

    def test_connect_timeout(self):
        exc = httpx.ConnectTimeout("Connection timed out")
        assert classify_error(exc) == ProbeErrorType.TIMEOUT

    def test_read_timeout(self):
        exc = httpx.ReadTimeout("Read timed out")
        assert classify_error(exc) == ProbeErrorType.TIMEOUT

    def test_generic_timeout(self):
        exc = httpx.TimeoutException("Timeout")
        assert classify_error(exc) == ProbeErrorType.TIMEOUT

    def test_connect_error_refused(self):
        exc = httpx.ConnectError("Connection refused")
        assert classify_error(exc) == ProbeErrorType.CONNECTION_REFUSED

    def test_connect_error_dns(self):
        exc = httpx.ConnectError("Name resolution failed")
        assert classify_error(exc) == ProbeErrorType.DNS_ERROR

    def test_connect_error_getaddrinfo(self):
        exc = httpx.ConnectError("[Errno -2] Name or service not known (getaddrinfo failed)")
        assert classify_error(exc) == ProbeErrorType.DNS_ERROR

    def test_connect_error_generic(self):
        exc = httpx.ConnectError("Some connection error")
        assert classify_error(exc) == ProbeErrorType.CONNECTION_REFUSED

    def test_ssl_error(self):
        exc = ssl.SSLError("SSL handshake failed")
        assert classify_error(exc) == ProbeErrorType.SSL_ERROR

    def test_ssl_in_message(self):
        exc = Exception("SSL certificate verify failed")
        assert classify_error(exc) == ProbeErrorType.SSL_ERROR

    def test_tls_in_message(self):
        exc = Exception("TLS handshake error")
        assert classify_error(exc) == ProbeErrorType.SSL_ERROR

    def test_certificate_in_message(self):
        exc = Exception("certificate has expired")
        assert classify_error(exc) == ProbeErrorType.SSL_ERROR

    def test_timeout_in_message(self):
        exc = Exception("Request timed out after 10s")
        assert classify_error(exc) == ProbeErrorType.TIMEOUT

    def test_refused_in_message(self):
        exc = Exception("Connection refused by host")
        assert classify_error(exc) == ProbeErrorType.CONNECTION_REFUSED

    def test_dns_in_message(self):
        exc = Exception("DNS lookup failed")
        assert classify_error(exc) == ProbeErrorType.DNS_ERROR

    def test_unknown_error(self):
        exc = Exception("Something completely unexpected")
        assert classify_error(exc) == ProbeErrorType.UNKNOWN


class TestProbeWorkerProbe:
    @pytest.mark.asyncio
    async def test_successful_probe(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ProbeWorker(
            trust_storage=mock_trust_storage,
            timeout=5.0,
            client=mock_client,
        )

        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.SUCCESS
        assert result.server_id == "svc-1"
        assert result.status_code == 200
        assert result.error is None
        assert result.latency_ms >= 0
        mock_trust_storage.store_probe_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_4xx_probe(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.HTTP_4XX
        assert result.status_code == 404
        assert result.error == "HTTP 404"

    @pytest.mark.asyncio
    async def test_5xx_probe(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.HTTP_5XX
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_timeout_probe(self, mock_trust_storage):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.TIMEOUT
        assert result.status_code == 0
        assert result.error is not None
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_connection_refused_probe(self, mock_trust_storage):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.CONNECTION_REFUSED
        assert result.status_code == 0

    @pytest.mark.asyncio
    async def test_dns_error_probe(self, mock_trust_storage):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Name resolution failed"))

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.DNS_ERROR

    @pytest.mark.asyncio
    async def test_ssl_error_probe(self, mock_trust_storage):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=ssl.SSLError("cert verify failed"))

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        result, error_type = await worker.probe("svc-1", "https://example.com")
        assert error_type == ProbeErrorType.SSL_ERROR

    @pytest.mark.asyncio
    async def test_probe_stores_result(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        await worker.probe("svc-1", "https://example.com")

        mock_trust_storage.store_probe_result.assert_called_once()
        stored = mock_trust_storage.store_probe_result.call_args[0][0]
        assert stored.server_id == "svc-1"
        assert stored.status_code == 200

    @pytest.mark.asyncio
    async def test_probe_creates_client_if_none(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("products.reputation.src.probe_worker.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.aclose = AsyncMock()
            MockClient.return_value = mock_instance

            worker = ProbeWorker(trust_storage=mock_trust_storage, timeout=5.0)
            result, error_type = await worker.probe("svc-1", "https://example.com")

            assert error_type == ProbeErrorType.SUCCESS
            mock_instance.aclose.assert_called_once()


class TestProbeWorkerBatch:
    @pytest.mark.asyncio
    async def test_probe_batch(self, mock_trust_storage):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        targets = [
            ("svc-1", "https://a.com"),
            ("svc-2", "https://b.com"),
            ("svc-3", "https://c.com"),
        ]
        results = await worker.probe_batch(targets)
        assert len(results) == 3
        assert all(r[1] == ProbeErrorType.SUCCESS for r in results)

    @pytest.mark.asyncio
    async def test_probe_batch_mixed_results(self, mock_trust_storage):
        responses = [
            MagicMock(status_code=200),
            MagicMock(status_code=500),
        ]

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=responses)

        worker = ProbeWorker(trust_storage=mock_trust_storage, client=mock_client)
        results = await worker.probe_batch([("svc-1", "https://a.com"), ("svc-2", "https://b.com")])
        assert results[0][1] == ProbeErrorType.SUCCESS
        assert results[1][1] == ProbeErrorType.HTTP_5XX

    @pytest.mark.asyncio
    async def test_probe_batch_empty(self, mock_trust_storage):
        worker = ProbeWorker(trust_storage=mock_trust_storage)
        results = await worker.probe_batch([])
        assert results == []
