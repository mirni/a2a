"""Tests for the ``a2a-mcp-server`` command-line entry point.

These exercise:

1. ``_parse_args`` — defaults, env fallbacks, and flag overrides.
2. ``main`` — early-exit when ``A2A_API_KEY`` is missing (stdio + http).
3. ``main`` — dispatches to the stdio / http runner based on ``--transport``.
4. ``_run_http`` — returns 2 with a helpful message when the HTTP extras
   are not installed.
5. ``python -m a2a_mcp_server`` — the ``__main__`` shim calls ``cli.main``.

The runners themselves are patched at the asyncio boundary so no real
sockets/stdio streams are opened in CI.
"""

from __future__ import annotations

import asyncio
import builtins
import runpy
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a_mcp_server import cli

# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


def test_parse_args_defaults(monkeypatch):
    """With no flags and no env, defaults are stdio + api.greenhelix.net."""
    for var in (
        "A2A_MCP_TRANSPORT",
        "A2A_BASE_URL",
        "A2A_API_KEY",
        "A2A_MCP_HOST",
        "A2A_MCP_PORT",
    ):
        monkeypatch.delenv(var, raising=False)

    args = cli._parse_args([])
    assert args.transport == "stdio"
    assert args.base_url == "https://api.greenhelix.net"
    assert args.api_key is None
    assert args.host == "127.0.0.1"
    assert args.port == 8765


def test_parse_args_env_fallback(monkeypatch):
    """Environment variables override defaults when flags are absent."""
    monkeypatch.setenv("A2A_MCP_TRANSPORT", "http")
    monkeypatch.setenv("A2A_BASE_URL", "https://gw.example.test")
    monkeypatch.setenv("A2A_API_KEY", "a2a_env_key")
    monkeypatch.setenv("A2A_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("A2A_MCP_PORT", "9000")

    args = cli._parse_args([])
    assert args.transport == "http"
    assert args.base_url == "https://gw.example.test"
    assert args.api_key == "a2a_env_key"
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_parse_args_flags_override_env(monkeypatch):
    """Explicit flags win over env vars."""
    monkeypatch.setenv("A2A_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("A2A_API_KEY", "env_key")

    args = cli._parse_args(
        [
            "--transport",
            "http",
            "--base-url",
            "https://flag.example.test",
            "--api-key",
            "flag_key",
            "--host",
            "1.2.3.4",
            "--port",
            "1234",
        ]
    )
    assert args.transport == "http"
    assert args.base_url == "https://flag.example.test"
    assert args.api_key == "flag_key"
    assert args.host == "1.2.3.4"
    assert args.port == 1234


def test_parse_args_rejects_unknown_transport(monkeypatch):
    monkeypatch.delenv("A2A_MCP_TRANSPORT", raising=False)
    with pytest.raises(SystemExit):
        cli._parse_args(["--transport", "websocket"])


def test_parse_args_version_flag_exits(capsys):
    """``--version`` prints the package version and exits cleanly."""
    with pytest.raises(SystemExit) as excinfo:
        cli._parse_args(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    from a2a_mcp_server._version import __version__

    assert __version__ in captured.out


# ---------------------------------------------------------------------------
# main — missing api key
# ---------------------------------------------------------------------------


def test_main_stdio_without_api_key_returns_2(monkeypatch, capsys):
    """``main`` prints an error and returns 2 when no api key is set (stdio)."""
    monkeypatch.delenv("A2A_API_KEY", raising=False)
    rc = cli.main(["--transport", "stdio"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "A2A_API_KEY is required" in err


def test_main_http_without_api_key_returns_2(monkeypatch, capsys):
    """``main`` prints an error and returns 2 when no api key is set (http)."""
    monkeypatch.delenv("A2A_API_KEY", raising=False)
    rc = cli.main(["--transport", "http"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "A2A_API_KEY is required" in err


# ---------------------------------------------------------------------------
# main — dispatches to the correct runner
# ---------------------------------------------------------------------------


def test_main_stdio_invokes_run_stdio(monkeypatch):
    """``main(--transport stdio)`` awaits ``_run_stdio`` and returns its rc."""
    monkeypatch.setenv("A2A_API_KEY", "a2a_test_key")

    fake_runner = AsyncMock(return_value=0)
    with patch.object(cli, "_run_stdio", fake_runner):
        rc = cli.main(["--transport", "stdio"])

    assert rc == 0
    fake_runner.assert_awaited_once()
    args = fake_runner.await_args.args[0]
    assert args.transport == "stdio"
    assert args.api_key == "a2a_test_key"


def test_main_http_invokes_run_http(monkeypatch):
    """``main(--transport http)`` awaits ``_run_http`` and returns its rc."""
    monkeypatch.setenv("A2A_API_KEY", "a2a_test_key")

    fake_runner = AsyncMock(return_value=0)
    with patch.object(cli, "_run_http", fake_runner):
        rc = cli.main(["--transport", "http", "--port", "8888"])

    assert rc == 0
    fake_runner.assert_awaited_once()
    args = fake_runner.await_args.args[0]
    assert args.transport == "http"
    assert args.port == 8888


# ---------------------------------------------------------------------------
# _run_http — ImportError fallback
# ---------------------------------------------------------------------------


def test_run_http_returns_2_when_http_extras_missing(monkeypatch, capsys):
    """Missing ``uvicorn``/``starlette`` → helpful error and rc=2."""
    monkeypatch.setenv("A2A_API_KEY", "a2a_test_key")

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name in {"uvicorn", "starlette.applications", "starlette.routing"} or name.startswith(
            "mcp.server.streamable_http_manager"
        ):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    args = cli._parse_args(["--transport", "http", "--api-key", "a2a_test_key"])
    rc = asyncio.run(cli._run_http(args))
    assert rc == 2
    err = capsys.readouterr().err
    assert "HTTP transport requires extras" in err
    assert "pip install" in err


# ---------------------------------------------------------------------------
# python -m a2a_mcp_server
# ---------------------------------------------------------------------------


def test_dunder_main_invokes_cli_main(monkeypatch):
    """``python -m a2a_mcp_server`` calls ``cli.main`` and re-raises its rc."""
    called = {}

    def fake_main(argv=None):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "main", fake_main)
    # Stub sys.argv so argparse doesn't see pytest's flags.
    monkeypatch.setattr(sys, "argv", ["a2a_mcp_server"])
    # Ensure a fresh import so the guard ``if __name__ == "__main__":`` runs.
    sys.modules.pop("a2a_mcp_server.__main__", None)
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("a2a_mcp_server", run_name="__main__")
    assert excinfo.value.code == 0


# ---------------------------------------------------------------------------
# _run_stdio — happy path (mocks the MCP server + stdio_server transport)
# ---------------------------------------------------------------------------


def test_run_stdio_happy_path(monkeypatch):
    """``_run_stdio`` wires GatewayClient → build_server → stdio_server."""
    args = cli._parse_args(
        [
            "--transport",
            "stdio",
            "--api-key",
            "a2a_test_key",
            "--base-url",
            "https://gw.example.test",
        ]
    )

    # Fake GatewayClient: async context manager returning itself.
    fake_client = MagicMock(name="GatewayClient")
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    gateway_cls = MagicMock(return_value=fake_client)
    monkeypatch.setattr(cli, "GatewayClient", gateway_cls)

    # Fake server returned by build_server.
    fake_server = MagicMock(name="Server")
    fake_server.create_initialization_options = MagicMock(return_value={"init": True})
    fake_server.run = AsyncMock(return_value=None)
    monkeypatch.setattr(cli, "build_server", lambda client: fake_server)

    # Fake stdio_server context manager yielding (read, write) streams.
    fake_stdio_cm = MagicMock(name="stdio_cm")
    fake_stdio_cm.__aenter__ = AsyncMock(return_value=("read-stream", "write-stream"))
    fake_stdio_cm.__aexit__ = AsyncMock(return_value=False)

    stdio_stub_module = types.SimpleNamespace(stdio_server=lambda: fake_stdio_cm)
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", stdio_stub_module)

    rc = asyncio.run(cli._run_stdio(args))
    assert rc == 0

    gateway_cls.assert_called_once_with(base_url="https://gw.example.test", api_key="a2a_test_key")
    fake_server.run.assert_awaited_once_with("read-stream", "write-stream", {"init": True})


# ---------------------------------------------------------------------------
# _run_http — happy path (mocks uvicorn + streamable http manager)
# ---------------------------------------------------------------------------


def test_run_http_happy_path(monkeypatch):
    """``_run_http`` wires a Starlette app and serves it via uvicorn."""
    args = cli._parse_args(
        [
            "--transport",
            "http",
            "--api-key",
            "a2a_test_key",
            "--base-url",
            "https://gw.example.test",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ]
    )

    # Fake GatewayClient: async context manager.
    fake_client = MagicMock(name="GatewayClient")
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    gateway_cls = MagicMock(return_value=fake_client)
    monkeypatch.setattr(cli, "GatewayClient", gateway_cls)

    # Fake MCP server.
    fake_server = MagicMock(name="Server")
    monkeypatch.setattr(cli, "build_server", lambda client: fake_server)

    # Fake StreamableHTTPSessionManager: .run() is an async ctxmgr,
    # .handle_request is a coroutine.
    fake_session_mgr = MagicMock(name="SessionManager")
    fake_session_mgr.handle_request = AsyncMock(return_value=None)
    fake_run_cm = MagicMock(name="session_run_cm")
    fake_run_cm.__aenter__ = AsyncMock(return_value=None)
    fake_run_cm.__aexit__ = AsyncMock(return_value=False)
    fake_session_mgr.run = MagicMock(return_value=fake_run_cm)
    session_mgr_cls = MagicMock(return_value=fake_session_mgr)

    streamable_module = types.SimpleNamespace(StreamableHTTPSessionManager=session_mgr_cls)
    monkeypatch.setitem(sys.modules, "mcp.server.streamable_http_manager", streamable_module)

    # Fake Starlette + Mount.
    starlette_cls = MagicMock(name="Starlette", return_value="fake-starlette-app")
    starlette_apps_module = types.SimpleNamespace(Starlette=starlette_cls)
    monkeypatch.setitem(sys.modules, "starlette.applications", starlette_apps_module)

    mount_cls = MagicMock(name="Mount", return_value="fake-mount")
    starlette_routing_module = types.SimpleNamespace(Mount=mount_cls)
    monkeypatch.setitem(sys.modules, "starlette.routing", starlette_routing_module)

    # Fake uvicorn.
    fake_server_instance = MagicMock(name="uvicorn.Server")
    fake_server_instance.serve = AsyncMock(return_value=None)
    uvicorn_stub = types.SimpleNamespace(
        Config=MagicMock(name="uvicorn.Config", return_value="fake-config"),
        Server=MagicMock(name="uvicorn.Server", return_value=fake_server_instance),
    )
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_stub)

    rc = asyncio.run(cli._run_http(args))
    assert rc == 0

    gateway_cls.assert_called_once_with(base_url="https://gw.example.test", api_key="a2a_test_key")
    session_mgr_cls.assert_called_once_with(app=fake_server, stateless=True)
    uvicorn_stub.Config.assert_called_once_with("fake-starlette-app", host="127.0.0.1", port=8765, log_level="info")
    uvicorn_stub.Server.assert_called_once_with("fake-config")
    fake_server_instance.serve.assert_awaited_once()


# ---------------------------------------------------------------------------
# cli module __main__ guard (line 130)
# ---------------------------------------------------------------------------


def test_cli_run_as_module(monkeypatch):
    """``python -m a2a_mcp_server.cli`` executes the ``if __name__ == ...`` guard."""
    monkeypatch.setattr(sys, "argv", ["a2a_mcp_server.cli", "--version"])
    # --version exits with 0 via argparse before touching any runner.
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("a2a_mcp_server.cli", run_name="__main__")
    assert excinfo.value.code == 0
