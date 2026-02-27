#!/usr/bin/env python3
import argparse
import base64
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv('.env')


def api_base() -> str:
    env = (os.getenv('EBAY_ENV') or 'production').lower()
    return 'https://api.ebay.com' if env.startswith('prod') else 'https://api.sandbox.ebay.com'


def auth_header_basic() -> str:
    cid = os.getenv('EBAY_CLIENT_ID')
    sec = os.getenv('EBAY_CLIENT_SECRET')
    if not cid or not sec:
        raise RuntimeError('Missing EBAY_CLIENT_ID/EBAY_CLIENT_SECRET')
    return base64.b64encode(f'{cid}:{sec}'.encode()).decode()


def refresh_access_token() -> str:
    refresh = os.getenv('EBAY_REFRESH_TOKEN')
    if not refresh:
        raise RuntimeError('Missing EBAY_REFRESH_TOKEN in .env')
    url = f"{api_base()}/identity/v1/oauth2/token"
    scopes = ' '.join([
        'https://api.ebay.com/oauth/api_scope',
        'https://api.ebay.com/oauth/api_scope/sell.account',
        'https://api.ebay.com/oauth/api_scope/sell.inventory',
        'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
        'https://api.ebay.com/oauth/api_scope/commerce.identity.readonly',
    ])
    r = requests.post(
        url,
        headers={
            'Authorization': f'Basic {auth_header_basic()}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh,
            'scope': scopes,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()['access_token']


def ebay_get(path: str, token: str, params=None):
    r = requests.get(
        f"{api_base()}{path}",
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        params=params or {},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def ebay_post(path: str, token: str, payload: dict):
    r = requests.post(
        f"{api_base()}{path}",
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps(payload),
        timeout=30,
    )
    r.raise_for_status()
    return r.json() if r.text else {}


def ebay_put(path: str, token: str, payload: dict):
    r = requests.put(
        f"{api_base()}{path}",
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps(payload),
        timeout=30,
    )
    r.raise_for_status()
    return r.json() if r.text else {}


def upload_images(token: str, image_paths: list[str]) -> list[str]:
    """Upload local images to eBay EPS via Trading API UploadSiteHostedPictures."""
    out = []
    ns = {'e': 'urn:ebay:apis:eBLBaseComponents'}
    headers = {
        'X-EBAY-API-CALL-NAME': 'UploadSiteHostedPictures',
        'X-EBAY-API-COMPATIBILITY-LEVEL': '1231',
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-IAF-TOKEN': token,
    }
    for p in image_paths:
        fp = Path(p)
        if not fp.exists():
            continue
        xml_payload = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<PictureName>{fp.name}</PictureName>'
            '<PictureSet>Standard</PictureSet>'
            '</UploadSiteHostedPicturesRequest>'
        )
        with fp.open('rb') as f:
            r = requests.post(
                'https://api.ebay.com/ws/api.dll',
                data={'XML Payload': xml_payload},
                files={'file': (fp.name, f, 'image/jpeg')},
                headers=headers,
                timeout=60,
            )
        if r.status_code >= 400:
            print(f"WARN image upload failed for {fp.name}: {r.status_code} {r.text[:200]}")
            continue
        try:
            root = ET.fromstring(r.text)
            full = root.find('.//e:FullURL', ns)
            ack = root.find('.//e:Ack', ns)
            if full is not None and full.text:
                out.append(full.text)
            else:
                print(f"WARN no FullURL for {fp.name} (Ack={ack.text if ack is not None else 'n/a'})")
        except Exception as ex:
            print(f"WARN parse failure for {fp.name}: {ex}")
    return out


def main():
    ap = argparse.ArgumentParser(description='Create an eBay draft offer via API')
    ap.add_argument('--sku', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--description', required=True)
    ap.add_argument('--price', required=True, type=float)
    ap.add_argument('--category-id', default='259104')
    ap.add_argument('--condition', default='GOOD')
    ap.add_argument('--qty', type=int, default=1)
    ap.add_argument('--images-dir', required=True)
    ap.add_argument('--marketplace', default='EBAY_US')
    args = ap.parse_args()

    token = refresh_access_token()

    # Listing policies (required for offers)
    fpol = ebay_get('/sell/account/v1/fulfillment_policy', token, {'marketplace_id': args.marketplace}).get('fulfillmentPolicies', [])
    ppol = ebay_get('/sell/account/v1/payment_policy', token, {'marketplace_id': args.marketplace}).get('paymentPolicies', [])
    rpol = ebay_get('/sell/account/v1/return_policy', token, {'marketplace_id': args.marketplace}).get('returnPolicies', [])
    if not (fpol and ppol and rpol):
        raise RuntimeError('Missing required eBay business policies (fulfillment/payment/return). Set them in seller account first.')

    fulfillment_policy_id = fpol[0]['fulfillmentPolicyId']
    payment_policy_id = ppol[0]['paymentPolicyId']
    return_policy_id = rpol[0]['returnPolicyId']

    img_dir = Path(args.images_dir)
    image_paths = [str(p) for p in sorted(img_dir.iterdir()) if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}]
    image_urls = upload_images(token, image_paths)

    product = {
        'title': args.title,
        'description': args.description,
    }
    if image_urls:
        product['imageUrls'] = image_urls

    inv_payload = {
        'availability': {'shipToLocationAvailability': {'quantity': args.qty}},
        'product': product,
    }
    ebay_put(f"/sell/inventory/v1/inventory_item/{args.sku}", token, inv_payload)

    offer_payload = {
        'sku': args.sku,
        'marketplaceId': args.marketplace,
        'format': 'FIXED_PRICE',
        'availableQuantity': args.qty,
        'categoryId': args.category_id,
        'listingDescription': args.description,
        'pricingSummary': {'price': {'value': f"{args.price:.2f}", 'currency': 'USD'}},
        'listingPolicies': {
            'fulfillmentPolicyId': fulfillment_policy_id,
            'paymentPolicyId': payment_policy_id,
            'returnPolicyId': return_policy_id,
        },
    }
    offer = ebay_post('/sell/inventory/v1/offer', token, offer_payload)

    # local ledger for one-click viewer
    ledger_dir = Path('data')
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / 'api_offer_ledger.jsonl'
    entry = {
        'createdAt': datetime.now(timezone.utc).isoformat(),
        'offerId': offer.get('offerId'),
        'sku': args.sku,
        'title': args.title,
        'price': f"{args.price:.2f}",
        'images': len(image_urls),
        'marketplace': args.marketplace,
        'categoryId': args.category_id,
    }
    with ledger_path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + "\n")

    print(json.dumps({'ok': True, 'offerId': offer.get('offerId'), 'sku': args.sku, 'uploadedImages': len(image_urls), 'ledger': str(ledger_path)}, indent=2))


if __name__ == '__main__':
    main()
