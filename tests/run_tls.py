#!/usr/bin/env python3
"""Test-only runner: serve the MCP server over TLS on 127.0.0.1:443.

Used to verify the template client (bin/client.py) end to end against
the local server, since the template client only accepts https URLs.
The certificate is self-signed, local-only, and never leaves tests/.

Usage:
    python3 tests/run_tls.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

import server  # noqa: E402

if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    app = server.mcp.streamable_http_app(
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1", "localhost"]
        )
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=443,
        ssl_keyfile=os.path.join(base, "tls", "server.key"),
        ssl_certfile=os.path.join(base, "tls", "server.crt"),
        log_level="warning",
    )
