#!/usr/bin/env python3
import base64
import csv
import glob
import json
import os
import re
import shutil
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv('.env')

BASE = 'https://api.ebay.com' if (os.getenv('EBAY_ENV') or 'production').lower().startswith('prod') else 'https://api.sandbox.ebay.com'
DB = Path('data/comics.db')
LEDGER = Path('data/api_offer_ledger.jsonl')
SRC_ROOT = Path('/home/john-dimm/Comics/comic-photos/PleaseGradeMe')
UP_ROOT = Path('/home/john-dimm/uploads')

SERIES_PREFIX = {
    'amazing spider-man': 'asm',
    'fantastic four': 'ff',
    'silver surfer': 'ss',
    'x-men': 'xmen',
}


def api_token():
    cid, sec, rt = os.getenv('EBAY_CLIENT_ID'), os.getenv('EBAY_CLIENT_SECRET'), os.getenv('EBAY_REFRESH_TOKEN')
    auth = base64.b64encode(f'{cid}:{sec}'.encode()).decode()
    scopes = ' '.join([
        'https://api.ebay.com/oauth/api_scope',
        'https://api.ebay.com/oauth/api_scope/sell.inventory',
        'https://api.ebay.com/oauth/api_scope/sell.account',
        'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
        'https://api.ebay.com/oauth/api_scope/commerce.identity.readonly',
    ])
    r = requests.post(
        BASE + '/identity/v1/oauth2/token',
        headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'},
        data={'grant_type': 'refresh_token', 'refresh_token': rt, 'scope': scopes},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()['access_token']


def issue_num(issue):
    m = re.search(r'\d+', str(issue or ''))
    return str(int(m.group(0))) if m else str(issue or '').strip()


def load_existing():
    out = set()
    if not LEDGER.exists():
        return out
    for line in LEDGER.read_text(encoding='utf-8').splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        t = (r.get('title') or '').lower()
        m = re.search(r'^(.*?)\s*#\s*(\d+)', t)
        if m:
            out.add((m.group(1).strip(), str(int(m.group(2)))))
    return out


def load_pgm_links():
    p = Path('data/comp_targets_unsold.csv')
    links = {}
    if not p.exists():
        return links
    with p.open(newline='', encoding='utf-8') as f:
        rd = csv.DictReader(f)
        for r in rd:
            t = (r.get('title') or '').strip().lower()
            i = issue_num(r.get('issue'))
            gc = (r.get('grade_class') or '').strip()
            u = (r.get('community_url') or '').strip()
            if t and i and u:
                links[(t, i, gc)] = u
                links[(t, i, 'any')] = u
    return links


def dynamic_ask_multiplier(row):
    market = float(row['market_price'] or 0)
    conf = (row['confidence'] or '').lower()
    slabbed = bool((row['cgc_cert'] or '').strip())
    active_count = int(row['active_count'] or 0)

    m = 1.05
    if slabbed:
        m += 0.03
    if conf == 'high':
        m += 0.02
    elif conf == 'low':
        m -= 0.02

    if market >= 1000:
        m += 0.03
    elif market >= 300:
        m += 0.01

    if active_count >= 8:
        m += 0.01
    elif active_count == 0:
        m -= 0.01

    return max(1.03, min(1.18, m))


def upload_eps(token, img_dir: Path):
    headers = {
        'X-EBAY-API-CALL-NAME': 'UploadSiteHostedPictures',
        'X-EBAY-API-COMPATIBILITY-LEVEL': '1231',
        'X-EBAY-API-SITEID': '0',
        'X-EBAY-API-IAF-TOKEN': token,
    }
    ns = {'e': 'urn:ebay:apis:eBLBaseComponents'}
    urls = []
    for p in sorted(glob.glob(str(img_dir / '*'))):
        if not os.path.isfile(p):
            continue
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<PictureName>{os.path.basename(p)}</PictureName>'
            '<PictureSet>Standard</PictureSet>'
            '</UploadSiteHostedPicturesRequest>'
        )
        try:
            with open(p, 'rb') as fh:
                r = requests.post('https://api.ebay.com/ws/api.dll', data={'XML Payload': xml}, files={'file': (os.path.basename(p), fh, 'image/jpeg')}, headers=headers, timeout=60)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.text)
            fu = root.find('.//e:FullURL', ns)
            if fu is not None and fu.text:
                urls.append(fu.text)
        except Exception:
            continue
    return urls


def main():
    token = api_token()
    H = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Content-Language': 'en-US'}

    fp = requests.get(BASE + '/sell/account/v1/fulfillment_policy', headers=H, params={'marketplace_id': 'EBAY_US'}, timeout=30).json()['fulfillmentPolicies'][0]['fulfillmentPolicyId']
    pp = requests.get(BASE + '/sell/account/v1/payment_policy', headers=H, params={'marketplace_id': 'EBAY_US'}, timeout=30).json()['paymentPolicies'][0]['paymentPolicyId']
    rp = requests.get(BASE + '/sell/account/v1/return_policy', headers=H, params={'marketplace_id': 'EBAY_US'}, timeout=30).json()['returnPolicies'][0]['returnPolicyId']

    existing = load_existing()
    pgm = load_pgm_links()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT c.id,c.title,c.issue,c.year,c.grade_numeric,c.qualified_flag,c.cgc_cert,c.status,
               ps.market_price, ps.confidence, ps.active_count
        FROM comics c
        LEFT JOIN price_suggestions ps ON ps.comic_id=c.id
        WHERE c.status IN ('unlisted','drafted')
          AND c.sold_price IS NULL
        ORDER BY c.title, c.issue_sort
        """
    ).fetchall()
    conn.close()

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    created = 0
    skipped = 0
    failed = 0

    for r in rows:
        t = (r['title'] or '').strip()
        t_key = t.lower()
        i = issue_num(r['issue'])
        if (t_key, i) in existing:
            skipped += 1
            continue
        if r['market_price'] is None:
            skipped += 1
            continue

        prefix = SERIES_PREFIX.get(t_key)
        folder = f"{prefix}{i}" if prefix else None
        up_dir = UP_ROOT / folder if folder else None
        src_dir = SRC_ROOT / folder if folder else None
        if up_dir and (not up_dir.exists()) and src_dir and src_dir.exists():
            up_dir.mkdir(parents=True, exist_ok=True)
            for p in src_dir.glob('*'):
                if p.is_file():
                    shutil.copy2(p, up_dir / p.name)

        image_urls = upload_eps(token, up_dir) if up_dir and up_dir.exists() else []

        grade = r['grade_numeric']
        slabbed = bool((r['cgc_cert'] or '').strip())
        qualified = bool(r['qualified_flag'])
        state = 'CGC' if slabbed else 'RAW'
        qtxt = ' Qualified' if qualified else ''
        year = r['year'] or ''
        title_line = f"{t} #{i} ({year}) Marvel Comics {state} {grade:g}{qtxt}".replace('  ', ' ').strip()
        cls = 'slabbed' if qualified else 'raw_community'
        link = pgm.get((t_key, i, cls)) or pgm.get((t_key, i, 'any')) or ''
        desc = (
            f"Why this issue matters: {t} #{i} is a classic back-issue with collector demand, and value is strongly grade-dependent.\n\n"
            "Please review all photos carefully and judge condition for yourself.\n\n"
            "Ships bagged/boarded with secure packaging.\n\n"
            + (f"Please Grade Me: {link}" if link else '')
        ).strip()
        # Use dynamic suggested ask logic, not a fixed multiplier.
        price = round(float(r['market_price']) * dynamic_ask_multiplier(r), 2)
        sku = f"{(folder or 'book').upper()}API{int(time.time())}"[:50]

        inv_payload = {
            'availability': {'shipToLocationAvailability': {'quantity': 1}},
            'product': {'title': title_line, 'description': desc, 'imageUrls': image_urls},
        }
        rinv = requests.put(BASE + f'/sell/inventory/v1/inventory_item/{sku}', headers=H, data=json.dumps(inv_payload), timeout=40)
        if rinv.status_code >= 300:
            failed += 1
            continue
        offer_payload = {
            'sku': sku,
            'marketplaceId': 'EBAY_US',
            'format': 'FIXED_PRICE',
            'availableQuantity': 1,
            'categoryId': '259104',
            'listingDescription': desc,
            'pricingSummary': {'price': {'value': f'{price:.2f}', 'currency': 'USD'}},
            'listingPolicies': {'fulfillmentPolicyId': fp, 'paymentPolicyId': pp, 'returnPolicyId': rp},
        }
        ro = requests.post(BASE + '/sell/inventory/v1/offer', headers=H, data=json.dumps(offer_payload), timeout=40)
        if ro.status_code >= 300:
            failed += 1
            continue
        oid = ro.json().get('offerId')
        entry = {
            'createdAt': datetime.now(timezone.utc).isoformat(),
            'offerId': oid,
            'sku': sku,
            'title': title_line,
            'price': f'{price:.2f}',
            'images': len(image_urls),
            'marketplace': 'EBAY_US',
            'categoryId': '259104',
        }
        with LEDGER.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
        created += 1
        existing.add((t_key, i))
        time.sleep(1)

    print(json.dumps({'created': created, 'skipped': skipped, 'failed': failed, 'total_rows': len(rows)}, indent=2))


if __name__ == '__main__':
    main()
