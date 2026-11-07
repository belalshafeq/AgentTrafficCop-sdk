"""Strict tests for newly added features: Verification, Named Keys, Session Logs."""

from __future__ import annotations

import pytest

from app.db import get_db
from app.userstore import user_store


class TestEmailVerification:
    def test_register_creates_unverified_user(self, client):
        """New users should start as unverified."""
        res = client.post("/v1/auth/register", json={"email": "test@example.com", "password": "password123"})
        assert res.status_code == 201
        assert res.json().get("api_key") is None
        
        user = user_store.get_user_by_email("test@example.com")
        assert user is not None
        assert user.is_verified is False

    def test_unverified_user_cannot_generate_key(self, client):
        """Attempting to generate a key without verifying should return 403."""
        res = client.post("/v1/auth/register", json={"email": "test@example.com", "password": "password123"})
        token = res.json()["access_token"]
        
        res2 = client.post("/v1/auth/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "My Key"})
        assert res2.status_code == 403
        assert "verify your email" in res2.json()["detail"]

    def test_email_verification_flow(self, client):
        """Test the full flow of getting a token and verifying."""
        client.post("/v1/auth/register", json={"email": "test@example.com", "password": "password123"})
        
        # Get the token directly from the DB
        token = user_store.get_verification_token("test@example.com")
        assert token is not None
        
        # Verify via the API
        res = client.post("/v1/auth/verify-email", json={"token": token})
        assert res.status_code == 200
        
        user = user_store.get_user_by_email("test@example.com")
        assert user.is_verified is True


class TestNamedApiKeys:
    def test_can_generate_named_key_after_verification(self, client):
        """Verified users can generate named keys, and they appear in /me."""
        res = client.post("/v1/auth/register", json={"email": "test2@example.com", "password": "password123"})
        token = res.json()["access_token"]
        
        # Verify via token
        v_token = user_store.get_verification_token("test2@example.com")
        client.post("/v1/auth/verify-email", json={"token": v_token})

        # Generate named key
        res2 = client.post("/v1/auth/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "LangGraph Prod"})
        assert res2.status_code == 200
        
        # Check /me
        res3 = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        data = res3.json()
        assert len(data["api_keys"]) == 1
        assert data["api_keys"][0]["name"] == "LangGraph Prod"

    def test_can_revoke_specific_key(self, client):
        """Test revoking a specific fingerprint."""
        res = client.post("/v1/auth/register", json={"email": "test3@example.com", "password": "password123"})
        token = res.json()["access_token"]
        
        v_token = user_store.get_verification_token("test3@example.com")
        client.post("/v1/auth/verify-email", json={"token": v_token})

        # Generate 1 key
        client.post("/v1/auth/keys", headers={"Authorization": f"Bearer {token}"}, json={"name": "Key 1"})
        
        me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert len(me["api_keys"]) == 1
        
        fp_to_delete = me["api_keys"][0]["fingerprint"]
        res_del = client.delete(f"/v1/auth/keys/{fp_to_delete}", headers={"Authorization": f"Bearer {token}"})
        assert res_del.status_code == 200
        
        me2 = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert len(me2["api_keys"]) == 0


class TestSessionLogs:
    def test_session_logs_empty(self, client):
        """No logs should exist initially."""
        # Must use JWT, not API key
        client.post("/v1/auth/register", json={"email": "logs1@example.com", "password": "password123"})
        login_res = client.post("/v1/auth/login", data={"username": "logs1@example.com", "password": "password123"})
        jwt = login_res.json()["access_token"]
        
        res = client.get("/v1/auth/session-logs", headers={"Authorization": f"Bearer {jwt}"})
        assert res.status_code == 200
        assert res.json()["logs"] == []

    def test_session_logs_after_route(self, client, sample_message):
        """After a successful route, a log should be created."""
        client.post("/v1/auth/register", json={"email": "log2@example.com", "password": "password123"})
        login_res = client.post("/v1/auth/login", data={"username": "log2@example.com", "password": "password123"})
        jwt = login_res.json()["access_token"]
        
        v_token = user_store.get_verification_token("log2@example.com")
        client.post("/v1/auth/verify-email", json={"token": v_token})
            
        key_res = client.post("/v1/auth/keys", headers={"Authorization": f"Bearer {jwt}"}, json={"name": "Test"})
        raw_key = key_res.json()["api_key"]
        new_headers = {"authorization": f"Bearer {raw_key}"}

        # 1. Make a successful route call
        client.post("/v1/route", json=sample_message, headers=new_headers)
        
        # Check logs using JWT
        logs = client.get("/v1/auth/session-logs", headers={"Authorization": f"Bearer {jwt}"}).json()["logs"]
        assert len(logs) == 1
        assert logs[0]["session_id"] == "test-session"
        assert logs[0]["status"] == "approved"

        # 2. Trip the breaker (repeated payload)
        from app.config import settings
        msg = dict(sample_message, payload={"test": "loop"})
        for _ in range(settings.max_repeated_hashes):
            client.post("/v1/route", json=msg, headers=new_headers)
            
        logs2 = client.get("/v1/auth/session-logs", headers={"Authorization": f"Bearer {jwt}"}).json()["logs"]
        assert any(l["status"] == "tripped" for l in logs2)