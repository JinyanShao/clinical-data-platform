from __future__ import annotations

from clinical_data_platform.operations import ContentSizeLimitMiddleware
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def test_content_size_limit_rejects_oversized_request_body() -> None:
    app = FastAPI()
    app.add_middleware(ContentSizeLimitMiddleware, max_bytes=4)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        response = client.post("/echo", content=b"12345")

    assert response.status_code == 413
    assert "4 bytes" in response.json()["detail"]
