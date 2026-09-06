import pytest


@pytest.mark.parametrize("origin", [
    "http://localhost:7921",
    "http://localhost:3000",
    "https://localhost:8443",
    "http://127.0.0.1:17921",
    "http://127.0.0.1:7921",
    "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef",
    "moz-extension://12345678-1234-1234-1234-123456789abc",
    "extension://custom-extension-id",
])
def test_cors_allowed_origins(client, origin: str):
    res = client.get("/api/status", headers={"Origin": origin})
    assert res.status_code == 200
    allow_origin = res.headers.get("Access-Control-Allow-Origin")
    assert allow_origin == origin


@pytest.mark.parametrize("origin", [
    "https://evil.com",
    "http://malicious.org",
    "http://localhost.evil.com",
    "http://127.0.0.1.attacker.com",
    "https://subdomain.localhost.com",
    "null",
])
def test_cors_disallowed_origins(client, origin: str):
    res = client.get("/api/status", headers={"Origin": origin})
    assert res.status_code == 200
    allow_origin = res.headers.get("Access-Control-Allow-Origin")
    # Disallowed origins must not receive Access-Control-Allow-Origin: * or the origin itself
    assert allow_origin is None or allow_origin != origin
    assert allow_origin != "*"


def test_cors_preflight_options_allowed(client):
    origin = "chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef"
    res = client.options(
        "/api/download",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("Access-Control-Allow-Origin") == origin


def test_cors_preflight_options_disallowed(client):
    origin = "https://evil.com"
    res = client.options(
        "/api/download",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    allow_origin = res.headers.get("Access-Control-Allow-Origin")
    assert allow_origin is None or allow_origin != origin
    assert allow_origin != "*"
