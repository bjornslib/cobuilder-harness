"""
Test cases for the API endpoint to ensure it returns 200 as required.
"""
import pytest
from fastapi.testclient import TestClient
from src.api_endpoint import app

client = TestClient(app)

def test_root_endpoint_returns_200():
    """Test that the root endpoint returns HTTP 200 status code."""
    response = client.get("/")
    assert response.status_code == 200
    assert "status" in response.json()
    assert "message" in response.json()

def test_health_endpoint_returns_200():
    """Test that the health endpoint returns HTTP 200 status code."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()
    assert response.json()["status"] == "healthy"

def test_api_returns_expected_structure():
    """Test that the API returns the expected response structure."""
    response = client.get("/")
    data = response.json()
    
    assert "status" in data
    assert "message" in data
    assert data["status"] == "ok"
    assert "API is running" in data["message"]
