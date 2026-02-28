#!/usr/bin/env python3
import base64
import csv
import json
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv('.env')

BASE = 'https://api.ebay.com' if (os.getenv('EBAY_ENV') or 'production').lower().startswith('prod') else 'https://api.sandbox.ebay.com'
LEDGER = Path('data/api_offer_ledger.jsonl')

KEY = {
    ('fantastic four', '55'): 'Fantastic Four #55 is a Lee/Kirby-era Silver Age issue featuring Klaw and Black Panther, with strong long-run collector demand.',
    ('fantastic four', '56'): 'Fantastic Four #56 is a Lee/Kirby-era Doctor Doom and Klaw storyline issue tied to early Wakanda/Black Panther continuity.',
    ('fantastic four', '58'): 'Fantastic Four #58 is a Silver Age Fantastic Four issue from the Inhumans/Doctor Doom era with consistent collector demand.',
    ('fantastic four', '78'): 'Fantastic Four #78 is a late Lee/Kirby-era Silver Age issue featuring Doctor Doom, with steady collector demand.',
    ('amazing spider-man', '20'): 'Amazing Spider-Man #20 is a key Silver Age issue featuring the first appearance and origin of the Scorpion (Mac Gargan).',
    ('amazing spider-man', '22'): 'Amazing Spider-Man #22 features the first appearance of Princess Python and remains a notable early Silver Age Spidey issue.',
    ('amazing spider-man', '23'): 'Amazing Spider-Man #23 is an early Green Goblin-era Silver Age issue with strong run-collector demand.',
    ('amazing spider-man', '24'): 'Amazing Spider-Man #24 is a classic Ditko-era Silver Age issue with continued collector demand for strong copies.',
    ('amazing spider-man', '25'): 'Amazing Spider-Man #25 features the first cameo appearance of Mary Jane Watson, a key moment in Spider-Man continuity.',
    ('amazing spider-man', '26'): 'Amazing Spider-Man #26 is a key Silver Age issue featuring the first appearance of the Crime-Master and an early Green Goblin appearance.',
    ('amazing spider-man', '27'): 'Amazing Spider-Man #27 is an early Silver Age Spider-Man issue tied to the Green Goblin/Crime-Master storyline.',
    ('x-men', '23'): 'X-Men #23 features the first full appearance of the Juggernaut, a major Silver Age villain key.',
}


def token():
    cid, sec, rt = os.getenv('EBAY_CLIENT_ID'), os.getenv('EBAY_CLIENT_SECRET'), os.getenv('EBAY_REFRESH_TOKEN')
    auth = base64.b64encode(f'{cid}:{sec}'.encode()).decode()
    scopes = ' '.join([
        'https://api.ebay.com/oauth/api_scope',
        'https://api.ebay.com/oauth/api_scope/sell.inventory',
        'https://api.ebay.com/oauth/api_scope/sell.account',
        'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
    ])
    r = requests.post(
        BASE + '/identity/v1/oauth2/token',
        headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'},
        data={'grant_type': 'refresh_token', 'refresh_token': rt, 'scope': scopes},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()['access_token']


def issue_num(s: str):
    m = re.search(r'\d+', s or '')
    return str(int(m.group(0))) if m else ''


def pgm_links():
    out = {}
    p = Path('data/comp_targets_unsold.csv')
    if not p.exists():
        return out
    with p.open(newline='', encoding='utf-8') as f:
        rd = csv.DictReader(f)
        for r in rd:
            t = (r.get('title') or '').strip().lower()
            i = issue_num(r.get('issue') or '')
            u = (r.get('community_url') or '').strip()
            cls = (r.get('grade_class') or '').strip()
            if t and i and u:
                out[(t, i, cls)] = u
                out[(t, i, 'any')] = u
    return out


def make_text(series: str, issue: str):
    s = series.lower().strip()
    i = issue_num(issue)
    if (s, i) in KEY:
        return KEY[(s, i)]

    try:
        inum = int(i)
    except Exception:
        inum = None

    if s == 'amazing spider-man':
        if inum is not None and inum <= 50:
            return f'Amazing Spider-Man #{i} is an early Silver Age issue from the Ditko/Romita era, one of Marvel\'s most collected runs.'
        return f'Amazing Spider-Man #{i} has consistent demand from run collectors, with higher-grade copies earning clear premiums.'

    if s == 'fantastic four':
        if inum is not None and inum <= 102:
            return f'Fantastic Four #{i} is from the Lee/Kirby Silver Age run, where eye appeal and grade drive strong collector demand.'
        return f'Fantastic Four #{i} has steady run-collector demand with value strongly tied to presentation and grade.'

    if s == 'x-men':
        return f'X-Men #{i} is from Marvel\'s core mutant run, where condition and page quality materially impact value.'

    return f'{series} #{i} has collector demand, with value primarily driven by grade, eye appeal, and scarcity in stronger condition.'


def parse_title_line(title: str):
    t = title or ''
    m = re.search(r'^(.*?)\s*#\s*(\d+)', t, flags=re.I)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2)


def main():
    if not LEDGER.exists():
        print(json.dumps({'updated': 0, 'reason': 'no ledger'}))
        return

    tk = token()
    H = {'Authorization': f'Bearer {tk}', 'Content-Type': 'application/json', 'Content-Language': 'en-US'}
    links = pgm_links()

    seen = set()
    updated = 0
    for line in LEDGER.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        oid = str(r.get('offerId') or '').strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)

        ro = requests.get(f'{BASE}/sell/inventory/v1/offer/{oid}', headers=H, timeout=20)
        if ro.status_code != 200:
            continue
        offer = ro.json()
        sku = offer.get('sku')
        if not sku:
            continue

        ri = requests.get(f'{BASE}/sell/inventory/v1/inventory_item/{sku}', headers=H, timeout=20)
        if ri.status_code != 200:
            continue
        inv = ri.json()

        title = ((inv.get('product') or {}).get('title') or r.get('title') or '')
        series, issue = parse_title_line(title)
        if not series or not issue:
            continue

        s = series.lower()
        cls = 'slabbed' if 'CGC' in title.upper() else 'raw_community'
        link = links.get((s, issue, cls)) or links.get((s, issue, 'any')) or ''
        why = make_text(series, issue)
        desc = (
            f"Why this issue matters: {why}\n\n"
            "Please review all photos carefully and judge condition for yourself.\n\n"
            "Ships bagged/boarded with secure packaging.\n\n"
            + (f"Please Grade Me: {link}" if link else "")
        ).strip()

        qty = (((inv.get('availability') or {}).get('shipToLocationAvailability') or {}).get('quantity') or 1)
        images = ((inv.get('product') or {}).get('imageUrls') or [])

        inv_payload = {
            'availability': {'shipToLocationAvailability': {'quantity': qty}},
            'product': {'title': title, 'description': desc, 'imageUrls': images},
        }
        pu = requests.put(f'{BASE}/sell/inventory/v1/inventory_item/{sku}', headers=H, data=json.dumps(inv_payload), timeout=30)
        if pu.status_code >= 300:
            continue

        offer['listingDescription'] = desc
        po = requests.put(f'{BASE}/sell/inventory/v1/offer/{oid}', headers=H, data=json.dumps(offer), timeout=30)
        if po.status_code < 300:
            updated += 1

    print(json.dumps({'updated': updated, 'checked': len(seen)}))


if __name__ == '__main__':
    main()
