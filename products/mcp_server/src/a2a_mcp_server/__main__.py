"""Allow ``python -m a2a_mcp_server`` invocation."""

from a2a_mcp_server.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
