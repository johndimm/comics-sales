#!/usr/bin/env python3
import argparse
import base64
import os
import sys
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv('.env')


def env_base() -> str:
    env = (os.getenv('EBAY_ENV') or 'PROD').lower()
    return 'https://api.ebay.com' if env.startswith('prod') else 'https://api.sandbox.ebay.com'


def auth_base() -> str:
    env = (os.getenv('EBAY_ENV') or 'PROD').lower()
    return 'https://auth.ebay.com' if env.startswith('prod') else 'https://auth.sandbox.ebay.com'


def creds_header() -> str:
    cid = os.getenv('EBAY_CLIENT_ID')
    sec = os.getenv('EBAY_CLIENT_SECRET')
    if not cid or not sec:
        raise RuntimeError('Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in .env')
    return base64.b64encode(f'{cid}:{sec}'.encode()).decode()


def default_scopes() -> str:
    return ' '.join([
        'https://api.ebay.com/oauth/api_scope',
        'https://api.ebay.com/oauth/api_scope/sell.account',
        'https://api.ebay.com/oauth/api_scope/sell.inventory',
        'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
        'https://api.ebay.com/oauth/api_scope/commerce.identity.readonly',
    ])


def print_auth_url() -> None:
    cid = os.getenv('EBAY_CLIENT_ID')
    ru = os.getenv('EBAY_REDIRECT_URI')
    if not cid or not ru:
        raise RuntimeError('Missing EBAY_CLIENT_ID or EBAY_REDIRECT_URI in .env')
    params = {
        'client_id': cid,
        'response_type': 'code',
        'redirect_uri': ru,
        'scope': default_scopes(),
        'prompt': 'login',
    }
    print(f"{auth_base()}/oauth2/authorize?{urlencode(params)}")


def exchange_code(code: str) -> None:
    ru = os.getenv('EBAY_REDIRECT_URI')
    if not ru:
        raise RuntimeError('Missing EBAY_REDIRECT_URI in .env')
    url = f"{env_base()}/identity/v1/oauth2/token"
    r = requests.post(
        url,
        headers={
            'Authorization': f'Basic {creds_header()}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': ru,
        },
        timeout=30,
    )
    print('status', r.status_code)
    print(r.text)


def refresh_token(refresh: str) -> None:
    url = f"{env_base()}/identity/v1/oauth2/token"
    r = requests.post(
        url,
        headers={
            'Authorization': f'Basic {creds_header()}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh,
            'scope': default_scopes(),
        },
        timeout=30,
    )
    print('status', r.status_code)
    print(r.text)


def main() -> int:
    p = argparse.ArgumentParser(description='Bootstrap eBay OAuth for Sell APIs')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('auth-url', help='Print OAuth authorize URL')

    ex = sub.add_parser('exchange', help='Exchange authorization code for tokens')
    ex.add_argument('--code', required=True)

    rf = sub.add_parser('refresh', help='Refresh access token from refresh token')
    rf.add_argument('--refresh-token', required=True)

    args = p.parse_args()
    if args.cmd == 'auth-url':
        print_auth_url()
    elif args.cmd == 'exchange':
        exchange_code(args.code)
    elif args.cmd == 'refresh':
        refresh_token(args.refresh_token)
    return 0


if __name__ == '__main__':
    sys.exit(main())
