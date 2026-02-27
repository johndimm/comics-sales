#!/usr/bin/env python3
"""Quick eBay auth check (Sandbox by default).

Usage:
  python scripts/test_ebay_auth.py

Requires in .env:
  EBAY_CLIENT_ID
  EBAY_CLIENT_SECRET
Optional:
  EBAY_ENV=sandbox|production (default: sandbox)
"""

import os
import sys
import base64
from dotenv import load_dotenv
import requests


def fail(msg: str, code: int = 1):
    print(f"❌ {msg}")
    raise SystemExit(code)


def main():
    load_dotenv()

    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    ebay_env = os.getenv("EBAY_ENV", "sandbox").strip().lower() or "sandbox"

    if not client_id:
        fail("Missing EBAY_CLIENT_ID in .env")
    if not client_secret:
        fail("Missing EBAY_CLIENT_SECRET in .env")

    if ebay_env == "production":
        oauth_url = "https://api.ebay.com/identity/v1/oauth2/token"
    else:
        oauth_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"

    raw = f"{client_id}:{client_secret}".encode("utf-8")
    basic = base64.b64encode(raw).decode("ascii")

    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }

    print(f"Testing eBay OAuth ({ebay_env})...")
    try:
        resp = requests.post(oauth_url, headers=headers, data=data, timeout=20)
    except Exception as e:
        fail(f"Request failed: {e}")

    if resp.status_code != 200:
        print(resp.text[:800])
        fail(f"OAuth failed with HTTP {resp.status_code}")

    payload = resp.json()
    token = payload.get("access_token")
    expires = payload.get("expires_in")

    if not token:
        print(resp.text[:800])
        fail("OAuth response did not include access_token")

    print("✅ OAuth success")
    print(f"Token type: {payload.get('token_type')}")
    print(f"Expires in: {expires} seconds")
    print(f"Access token preview: {token[:18]}...{token[-8:]}")


if __name__ == "__main__":
    main()
