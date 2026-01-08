import httpx
from fastapi import FastAPI


async def init_http_client(app: FastAPI) -> None:
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    )

async def close_http_client(app: FastAPI) -> None:
    client: httpx.AsyncClient = app.state.http_client
    await client.aclose()

async def init_and_get_http_client() -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    )
    return client

async def close_http_client_on_client(client: httpx.AsyncClient) -> None:
    await client.aclose()