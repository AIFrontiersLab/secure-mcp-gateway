"""Tests for Secure MCP Gateway."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_valid_request():
    response = client.post(
        "/mcp/connect",
        json={
            "agent_id": "agent-alpha",
            "tool_name": "data-lookup",
            "payload": {"key": "value"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["processed"] is True
    assert "session_id" in data["data"]


def test_denied_request():
    response = client.post(
        "/mcp/connect",
        json={
            "agent_id": "agent-beta",
            "tool_name": "data-lookup",
            "payload": {"key": "value"},
        },
    )
    assert response.status_code == 403
    assert "Access Denied" in response.json()["detail"]


def test_audit_logs_populated():
    client.post(
        "/mcp/connect",
        json={
            "agent_id": "agent-alpha",
            "tool_name": "write-data",
            "payload": {"op": "upsert"},
        },
    )
    response = client.get("/audit/logs")
    assert response.status_code == 200
    logs = response.json()["logs"]
    assert len(logs) > 0
    last_log = logs[-1]
    assert "event" in last_log
    assert "timestamp" in last_log
    assert "request_id" in last_log
