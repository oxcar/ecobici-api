"""
Tests para la API de prediccion.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """Cliente HTTP asincrono para tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    """Test de la ruta raiz."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    """Test del health check."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "models_loaded" in data
    assert "gbfs_available" in data


@pytest.mark.asyncio
async def test_stations_list(client: AsyncClient):
    """Test de listado de estaciones."""
    response = await client.get("/api/v1/stations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_station_not_found(client: AsyncClient):
    """Test de estacion no encontrada."""
    response = await client.get("/api/v1/stations/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_predict_not_found(client: AsyncClient):
    """Test de prediccion con estacion no encontrada."""
    response = await client.get("/api/v1/predict/99999")
    assert response.status_code == 404
