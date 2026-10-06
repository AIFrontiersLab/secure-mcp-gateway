"""Secure MCP Gateway — Phase 1 foundation.

Gateway ingress, AuthZ, session store, and append-only audit logging.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# --- Models ---

class MCPRequest(BaseModel):
    agent_id: str = Field(..., description="Authenticated agent identity")
    tool_name: str = Field(..., description="Target tool name")
    payload: dict[str, Any] = Field(default_factory=dict, description="Tool input payload")


class MCPResponse(BaseModel):
    request_id: str
    status: str
    data: Optional[dict[str, Any]] = None
    audit_id: str


class AuthZPolicy(BaseModel):
    agent_id: str
    tool_name: str
    allowed: bool
    cost_factor: float = 1.0


class SessionStore:
    """Session affinity store. Production deployments typically use Redis."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}

    def create_session(self, agent_id: str) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "agent_id": agent_id,
            "created_at": time.time(),
            "status": "active",
        }
        return session_id

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        return self.sessions.get(session_id)

    def destroy_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)


class AuditLog:
    """Append-only audit trail (WORM-style for local development)."""

    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    def write(self, event: dict[str, Any]) -> None:
        self.logs.append(dict(event))

    def get_logs(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.logs]


class AuthZService:
    """Role/tool policy checker with default deny."""

    def __init__(self) -> None:
        self.policies: list[AuthZPolicy] = [
            AuthZPolicy(agent_id="agent-alpha", tool_name="data-lookup", allowed=True, cost_factor=1.0),
            AuthZPolicy(agent_id="agent-beta", tool_name="data-lookup", allowed=False),
            AuthZPolicy(agent_id="agent-alpha", tool_name="write-data", allowed=True, cost_factor=2.0),
        ]

    def check(self, agent_id: str, tool_name: str) -> AuthZPolicy:
        for policy in self.policies:
            if policy.agent_id == agent_id and policy.tool_name == tool_name:
                return policy
        return AuthZPolicy(agent_id=agent_id, tool_name=tool_name, allowed=False)


app = FastAPI(
    title="Secure MCP Gateway",
    description="Zero-trust gateway for enterprise MCP tool access",
    version="0.1.0",
)

session_store = SessionStore()
audit_log = AuditLog()
authz_service = AuthZService()


@app.post("/mcp/connect", response_model=MCPResponse)
async def connect(request: MCPRequest) -> MCPResponse:
    """Validate identity/policy, create a session, and audit the decision."""
    request_id = str(uuid.uuid4())
    start_time = time.time()

    policy = authz_service.check(request.agent_id, request.tool_name)
    if not policy.allowed:
        audit_log.write(
            {
                "event": "auth_denied",
                "request_id": request_id,
                "agent_id": request.agent_id,
                "tool_name": request.tool_name,
                "timestamp": time.time(),
            }
        )
        raise HTTPException(status_code=403, detail="Access Denied by Policy")

    session_id = session_store.create_session(request.agent_id)
    result_data = {
        "processed": True,
        "original_payload": request.payload,
        "session_id": session_id,
    }

    audit_log.write(
        {
            "event": "request_success",
            "request_id": request_id,
            "session_id": session_id,
            "agent_id": request.agent_id,
            "tool_name": request.tool_name,
            "cost_factor": policy.cost_factor,
            "duration_sec": time.time() - start_time,
            "timestamp": time.time(),
        }
    )

    return MCPResponse(
        request_id=request_id,
        status="success",
        data=result_data,
        audit_id=str(len(audit_log.get_logs())),
    )


@app.get("/audit/logs")
async def get_audit_logs() -> dict[str, list[dict[str, Any]]]:
    """Return the append-only audit trail."""
    return {"logs": audit_log.get_logs()}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def demo() -> None:
    """Run a local allow/deny walkthrough without a long-lived server."""
    import json

    from fastapi.testclient import TestClient

    print("--- Secure MCP Gateway Demo ---")
    client = TestClient(app)

    print("\n[1] Sending valid request from agent-alpha...")
    resp1 = client.post(
        "/mcp/connect",
        json={
            "agent_id": "agent-alpha",
            "tool_name": "data-lookup",
            "payload": {"key": "value"},
        },
    )
    print(f"Status: {resp1.status_code}")
    print(f"Response: {json.dumps(resp1.json(), indent=2)}")

    print("\n[2] Sending denied request from agent-beta...")
    resp2 = client.post(
        "/mcp/connect",
        json={
            "agent_id": "agent-beta",
            "tool_name": "data-lookup",
            "payload": {"key": "value"},
        },
    )
    print(f"Status: {resp2.status_code}")
    print(f"Response: {json.dumps(resp2.json(), indent=2)}")

    print("\n[3] Retrieving audit logs...")
    logs = client.get("/audit/logs").json()["logs"]
    print(f"Total audit entries: {len(logs)}")
    for i, entry in enumerate(logs, start=1):
        print(f"  Log {i}: {entry['event']} - Agent: {entry['agent_id']}")

    print("\n--- Demo Complete ---")


if __name__ == "__main__":
    demo()
