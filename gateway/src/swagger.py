"""Swagger UI endpoint — serves interactive API explorer at /docs."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse

SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>A2A Commerce Platform — API Docs</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: '/v1/openapi.json',
      dom_id: '#swagger-ui',
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
      layout: 'BaseLayout',
    });
  </script>
</body>
</html>"""


async def swagger_ui_handler(request: Request) -> HTMLResponse:
    """Serve Swagger UI at /docs."""
    return HTMLResponse(SWAGGER_HTML)
