from fastapi import FastAPI, Query, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from html import escape, unescape
from functools import lru_cache
from pathlib import Path
import json
import re
import csv
import math
from app.db import get_conn
from dotenv import load_dotenv
import os
import base64
import requests
from datetime import datetime
from urllib.parse import quote, unquote

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
app = FastAPI(title="Comics Sales MVP")

# Defaults (UI can override per request)
DEFAULTS = {
    "platform_fee_rate": 0.13,
    "avg_ship_cost": 15.0,
    "cgc_grading_cost": 45.0,
    "cgc_ship_insure_cost": 20.0,
    "time_penalty_rate": 0.05,
    "slab_lift_min_dollars": 150.0,
    "slab_lift_min_pct": 0.20,
}

PHOTOS_ROOT = Path("/home/john-dimm/Comics")
V2_IMAGES_CSV = PHOTOS_ROOT / "marvel" / "data" / "v2" / "comics-images.csv"
V2_COMICS_CSV = PHOTOS_ROOT / "marvel" / "data" / "v2" / "comics.csv"
LOCAL_PHOTO_DIRS = [
    PHOTOS_ROOT / "comic-photos" / "PleaseGradeMe",
    PHOTOS_ROOT / "marvel" / "data" / "v2" / "photos-cropped",
    PHOTOS_ROOT / "marvel" / "data" / "v2" / "photos",
]
SERIES_PREFIX = {
    "amazing spider-man": "asm",
    "fantastic four": "ff",
    "silver surfer": "ss",
    "x-men": "xmen",
}
PGM_SERIES_PREFIX = {
    "asm": "Amazing Spider-Man",
    "asmannual": "Amazing Spider-Man Annual",
    "ff": "Fantastic Four",
    "ffannual": "Fantastic Four Annual",
}

KEY_ISSUE_NOTES = {
    ("amazing spider-man", "14"): "First appearance of Green Goblin.",
    ("amazing spider-man", "20"): "Classic Ditko-era early ASM issue; strong Silver Age demand.",
    ("amazing spider-man", "31"): "First Gwen Stacy and Harry Osborn (cameo).",
    ("amazing spider-man", "39"): "Green Goblin identity revealed.",
    ("fantastic four", "48"): "First Silver Surfer and first Galactus (cameo).",
    ("fantastic four", "49"): "First full Galactus.",
    ("fantastic four", "50"): "Silver Surfer turns against Galactus.",
    ("fantastic four", "52"): "First appearance of Black Panther.",
    ("fantastic four", "55"): "Fantastic Four #55 is a Lee/Kirby-era Silver Age issue featuring Klaw and Black Panther, with strong long-run collector demand.",
    ("fantastic four", "78"): "Late Lee/Kirby-era Fantastic Four issue featuring Doctor Doom, with steady Silver Age collector demand.",
}

if PHOTOS_ROOT.exists():
    app.mount("/local-photos", StaticFiles(directory=str(PHOTOS_ROOT)), name="local-photos")


def grade_class_sql():
    return """
    CASE
      WHEN c.cgc_cert IS NOT NULL AND TRIM(c.cgc_cert) <> '' THEN 'slabbed'
      WHEN (c.cgc_cert IS NULL OR TRIM(c.cgc_cert) = '')
           AND c.community_url IS NOT NULL AND TRIM(c.community_url) <> '' THEN 'raw_community'
      ELSE 'raw_no_community'
    END
    """


def estimate_slab_multiplier(grade_numeric, qualified_flag):
    if qualified_flag:
        return 1.0
    g = grade_numeric or 0
    if g >= 8.0:
        return 1.35
    if g >= 6.0:
        return 1.25
    if g >= 4.0:
        return 1.15
    return 1.05


def recommend_channel(market_price: float | None, confidence: str | None, is_key: bool = False):
    p = market_price or 0
    if p >= 2500:
        return "heritage_or_major_auction"
    if p >= 500:
        return "ebay_fixed_price_offers"
    if p >= 150:
        return "ebay_or_facebook_groups"
    return "ebay"


def compute_trend(prices_desc: list[float]):
    vals = [float(x) for x in prices_desc if x is not None and x > 0]
    if len(vals) < 8:
        return ("insufficient", None)

    recent = vals[:5]
    prior = vals[5:10]
    if len(prior) < 3:
        return ("insufficient", None)

    recent_med = sorted(recent)[len(recent) // 2]
    prior_med = sorted(prior)[len(prior) // 2]
    if prior_med <= 0:
        return ("insufficient", None)

    pct = ((recent_med - prior_med) / prior_med) * 100.0
    if pct >= 8:
        label = "rising"
    elif pct <= -8:
        label = "falling"
    else:
        label = "flat"
    return (label, round(pct, 1))


def _normalize_photo_url(url: str):
    u = (url or "").strip()
    if not u:
        return u
    # Normalize older GitHub raw refs paths that 404 in browser.
    u = u.replace("/refs/heads/main/", "/main/")
    return u


def _parse_pgm_folder(name: str):
    n = (name or "").strip().lower()
    for prefix in sorted(PGM_SERIES_PREFIX.keys(), key=len, reverse=True):
        if n.startswith(prefix):
            num = n[len(prefix):]
            if num.isdigit():
                return PGM_SERIES_PREFIX[prefix], str(int(num))
    return None, None


@lru_cache(maxsize=1)
def _pgm_folder_map():
    out = {}
    root = PHOTOS_ROOT / "comic-photos" / "PleaseGradeMe"
    if not root.exists():
        return out
    for d in root.iterdir():
        if not d.is_dir():
            continue
        title, issue = _parse_pgm_folder(d.name)
        if not title:
            continue
        key = (title.lower(), issue)
        urls = []
        for p in d.rglob("*"):
            if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
                continue
            try:
                rel = p.relative_to(PHOTOS_ROOT)
                urls.append(f"/local-photos/{rel.as_posix()}")
            except Exception:
                pass
        if urls:
            out[key] = sorted(urls)
    return out


@lru_cache(maxsize=1)
def _v2_images_map():
    out = {}
    if not V2_IMAGES_CSV.exists():
        return out
    try:
        with V2_IMAGES_CSV.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                cid = (row.get("comic_id") or "").strip()
                url = _normalize_photo_url((row.get("photo") or "").strip())
                if not cid or not url:
                    continue
                out.setdefault(cid, []).append(url)
    except Exception:
        return {}
    return out


@lru_cache(maxsize=1)
def _all_local_photo_paths():
    out = []
    for d in LOCAL_PHOTO_DIRS:
        if d.exists():
            out.extend([p for p in d.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"}])
    return out


def _marvel_thumb_from_id(marvel_id: str | None):
    if not marvel_id:
        return []
    mid = str(marvel_id).strip()
    if not mid.isdigit():
        return []
    jf = PHOTOS_ROOT / "marvel" / "data" / "v2" / "marvel" / f"{mid}.json"
    if not jf.exists():
        return []
    try:
        data = json.loads(jf.read_text())
        t = data.get("thumbnail") or {}
        if t.get("path") and t.get("extension"):
            return [f"{t['path']}.{t['extension']}"]
    except Exception:
        return []
    return []


def pick_cover_photo(urls: list[str]):
    for u in urls:
        lu = u.lower()
        if any(x in lu for x in ["/front", "_front", "front.", " cover", "-f.", "f.jpg", "f.jpeg", "f.png"]):
            return u
    for u in urls:
        lu = u.lower()
        if any(x in lu for x in ["back", "_b.", "-b.", "pinup", "inside", "rear"]):
            continue
        return u
    return urls[0] if urls else None


def photo_candidates(title: str | None, issue: str | None, marvel_id: str | None):
    cands = []

    title_s = (title or "").strip()
    issue_s = str(issue or "").strip()
    folder_key = (title_s.lower(), issue_s)
    if folder_key in _pgm_folder_map():
        cands.extend(_pgm_folder_map()[folder_key])

    mid = (str(marvel_id).strip() if marvel_id is not None else "")
    if mid and mid in _v2_images_map():
        cands.extend(_v2_images_map().get(mid, []))
    cands.extend(_marvel_thumb_from_id(marvel_id))

    t = (title or "").lower()
    issue_s = str(issue or "").strip().lower()
    issue_num = re.sub(r"[^0-9]", "", issue_s)
    prefix = None
    for k, v in SERIES_PREFIX.items():
        if k in t:
            prefix = v
            break

    for p in _all_local_photo_paths():
        name = p.stem.lower()
        ok = False

        # If we know the series prefix (xmen/ff/asm...), require it so issue-number-only
        # matches don't leak covers from other series (e.g., X-Men #10 -> FF #10).
        if prefix and issue_num:
            if f"{prefix}{issue_num}" in name:
                ok = True
        else:
            if issue_num and re.search(rf"(?:^|[^0-9]){re.escape(issue_num)}(?:[^0-9]|$)", name):
                ok = True

        if ok:
            try:
                rel = p.relative_to(PHOTOS_ROOT)
                cands.append(f"/local-photos/{rel.as_posix()}")
            except Exception:
                pass

    # dedupe preserve order
    seen = set()
    out = []
    for u in cands:
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out


@lru_cache(maxsize=1)
def _v2_comics_desc_map():
    out = {}
    if not V2_COMICS_CSV.exists():
        return out
    try:
        with V2_COMICS_CSV.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                cid = (row.get("id") or "").strip()
                desc = (row.get("description") or "").strip()
                if cid and desc and desc.lower() != "none":
                    out[cid] = desc
    except Exception:
        return {}
    return out


def issue_importance_text(title: str | None, issue: str | None, marvel_id: str | None):
    t = (title or "").strip().lower()
    iss = str(issue or "").strip().lower()
    key = (t, iss)
    if key in KEY_ISSUE_NOTES:
        return KEY_ISSUE_NOTES[key]

    mid = (str(marvel_id).strip() if marvel_id is not None else "")
    desc = _v2_comics_desc_map().get(mid)
    if desc:
        return desc

    # Better non-boilerplate fallbacks by series/era
    try:
        inum = int(re.search(r"\d+", iss).group(0))
    except Exception:
        inum = None

    if t == "fantastic four":
        if inum is not None and inum <= 102:
            return (
                f"Fantastic Four #{iss} is a Silver Age Lee/Kirby-era issue; even non-first-appearance books from this run hold "
                "collector demand, with value driven by presentation and grade." 
            )
        return f"Fantastic Four #{iss} has steady collector interest, with upside tied to grade and eye appeal."

    if t == "amazing spider-man":
        if inum is not None and inum <= 50:
            return (
                f"Amazing Spider-Man #{iss} is from the early Ditko/Romita Silver Age run, a heavily collected era where "
                "strong-presenting copies command premiums."
            )
        return f"Amazing Spider-Man #{iss} has consistent demand from run collectors, with grade driving most of the spread."

    if t == "x-men":
        return f"X-Men #{iss} is from Marvel's core mutant run, where condition and page quality strongly influence value."

    return f"{title or 'This issue'} has collector demand, with value primarily driven by grade, eye appeal, and scarcity in higher-condition copies."


def dynamic_ask_multiplier(r: dict):
    market = float(r.get("market_price") or 0)
    conf = (r.get("confidence") or "").lower()
    grade_class = (r.get("grade_class") or "")
    active_count = int(r.get("active_count") or 0)

    m = 1.05
    if grade_class == "slabbed":
        m += 0.03
    if conf == "high":
        m += 0.02
    elif conf == "low":
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


def decision_for_row(r: dict, assumptions: dict):
    market = r.get("market_price")
    grade_class = r.get("grade_class")
    status = r.get("status")
    grade = r.get("grade_numeric")
    qualified_flag = r.get("qualified_flag") or 0

    if status == "sold":
        return {"action": "already_sold"}

    if grade_class == "slabbed":
        target_mult = dynamic_ask_multiplier(r)
        active_anchor = r.get("active_anchor_price")
        anchor_mult = 1.3 if (market or 0) >= 500 else 1.2
        model_anchor = round((market or 0) * anchor_mult, 2) if market else None
        anchor_price = model_anchor
        if active_anchor is not None and model_anchor is not None:
            anchor_price = round(max(model_anchor, active_anchor), 2)
        elif active_anchor is not None:
            anchor_price = round(float(active_anchor), 2)

        return {
            "target_price": round((market or 0) * target_mult, 2) if market else None,
            "floor_price": round((market or 0) * (0.92 if (r.get("confidence") == "high") else 0.88), 2) if market else None,
            "anchor_price": anchor_price,
            "channel_hint": recommend_channel(market, r.get("confidence")),
            "action": "list_now_slabbed",
        }

    if market is None:
        if grade_class == "raw_no_community":
            return {"channel_hint": "prep_community_then_ebay", "action": "get_community_grade"}
        return {"channel_hint": "ebay_fixed_price_offers", "action": "needs_comps"}

    net_raw = market * (1 - assumptions["platform_fee_rate"]) - assumptions["avg_ship_cost"]
    slab_mult = estimate_slab_multiplier(grade, qualified_flag)
    expected_slab_gross = market * slab_mult
    net_slabbed = (
        expected_slab_gross * (1 - assumptions["platform_fee_rate"])
        - assumptions["avg_ship_cost"]
        - assumptions["cgc_grading_cost"]
        - assumptions["cgc_ship_insure_cost"]
        - (expected_slab_gross * assumptions["time_penalty_rate"])
    )

    slab_lift = net_slabbed - net_raw
    slab_lift_pct = slab_lift / net_raw if net_raw > 0 else 0

    if (
        slab_lift >= assumptions["slab_lift_min_dollars"]
        and slab_lift_pct >= assumptions["slab_lift_min_pct"]
    ):
        action = "slab_candidate"
    elif grade_class == "raw_no_community":
        action = "get_community_grade"
    else:
        action = "sell_raw_now"

    anchor_mult = 1.3 if (market or 0) >= 500 else 1.2
    model_anchor = round((market or 0) * anchor_mult, 2) if market else None
    active_anchor = r.get("active_anchor_price")
    anchor_price = model_anchor
    if active_anchor is not None and model_anchor is not None:
        anchor_price = round(max(model_anchor, active_anchor), 2)
    elif active_anchor is not None:
        anchor_price = round(float(active_anchor), 2)
    target_mult = dynamic_ask_multiplier(r)
    target_price = round((market or 0) * target_mult, 2) if market else None
    floor_price = round((market or 0) * (0.92 if (r.get("confidence") == "high") else 0.88), 2) if market else None

    return {
        "net_raw": round(net_raw, 2),
        "net_slabbed": round(net_slabbed, 2),
        "slab_lift": round(slab_lift, 2),
        "slab_lift_pct": round(slab_lift_pct * 100, 1),
        "anchor_price": anchor_price,
        "target_price": target_price,
        "floor_price": floor_price,
        "channel_hint": recommend_channel(market, r.get("confidence")),
        "action": action,
    }


@app.get("/api/decision-queue")
def decision_queue(
    limit: int = Query(default=300, le=1000),
    action: str | None = None,
    grade_classes: str | None = None,
    sort_by: str = "priority",
    min_market: float = 0,
    platform_fee_rate: float = DEFAULTS["platform_fee_rate"],
    avg_ship_cost: float = DEFAULTS["avg_ship_cost"],
    cgc_grading_cost: float = DEFAULTS["cgc_grading_cost"],
    cgc_ship_insure_cost: float = DEFAULTS["cgc_ship_insure_cost"],
    time_penalty_rate: float = DEFAULTS["time_penalty_rate"],
    slab_lift_min_dollars: float = DEFAULTS["slab_lift_min_dollars"],
    slab_lift_min_pct: float = DEFAULTS["slab_lift_min_pct"],
):
    assumptions = {
        "platform_fee_rate": platform_fee_rate,
        "avg_ship_cost": avg_ship_cost,
        "cgc_grading_cost": cgc_grading_cost,
        "cgc_ship_insure_cost": cgc_ship_insure_cost,
        "time_penalty_rate": time_penalty_rate,
        "slab_lift_min_dollars": slab_lift_min_dollars,
        "slab_lift_min_pct": slab_lift_min_pct,
    }

    conn = get_conn()
    rows = conn.execute(
        f"""
        SELECT c.id, c.title, c.issue, c.year, c.marvel_id, c.grade_numeric, c.status, c.qualified_flag,
               {grade_class_sql()} AS grade_class,
               ps.market_price, ps.universal_market_price, ps.qualified_market_price, ps.active_anchor_price, ps.active_count, ps.confidence, ps.basis_count
        FROM comics c
        LEFT JOIN price_suggestions ps ON ps.comic_id = c.id
        WHERE c.status IN ('unlisted','drafted')
          AND c.sold_price IS NULL
        ORDER BY c.title, c.issue_sort
        """
    ).fetchall()

    trend_map = {}
    comic_ids = [r["id"] for r in rows]
    if comic_ids:
        placeholders = ",".join(["?"] * len(comic_ids))
        comp_rows = conn.execute(
            f"""
            SELECT comic_id, price, id
            FROM market_comps
            WHERE listing_type='sold'
              AND price IS NOT NULL
              AND comic_id IN ({placeholders})
            ORDER BY comic_id, id DESC
            """,
            comic_ids,
        ).fetchall()
        grouped = {}
        for cr in comp_rows:
            grouped.setdefault(cr["comic_id"], []).append(cr["price"])
        for cid, prices in grouped.items():
            trend_map[cid] = compute_trend(prices)

    conn.close()

    selected_classes = None
    if grade_classes:
        selected_classes = {x.strip() for x in grade_classes.split(",") if x.strip()}

    offer_idx = _api_offer_index()

    out = []
    for row in rows:
        d = dict(row)
        d.update(decision_for_row(d, assumptions))
        if action and d.get("action") != action:
            continue
        if selected_classes and d.get("grade_class") not in selected_classes:
            continue
        if (d.get("market_price") or 0) < min_market:
            continue
        trend_label, trend_pct = trend_map.get(d.get("id"), ("insufficient", None))
        d["trend"] = trend_label
        d["trend_pct"] = trend_pct
        pics = photo_candidates(d.get("title"), d.get("issue"), d.get("marvel_id"))
        d["thumb_url"] = pick_cover_photo(pics) if pics else None
        d["importance_text"] = issue_importance_text(d.get("title"), d.get("issue"), d.get("marvel_id"))
        key = ((d.get("title") or "").strip().lower(), _parse_issue_num(d.get("issue")))
        d["api_offer_id"] = offer_idx.get(key)
        out.append(d)

    priority = {
        "list_now_slabbed": 1,
        "slab_candidate": 2,
        "sell_raw_now": 3,
        "get_community_grade": 4,
        "needs_comps": 5,
    }

    if sort_by == "fmv_desc":
        out.sort(key=lambda x: (-(x.get("market_price") or 0), priority.get(x.get("action"), 99)))
    else:
        out.sort(key=lambda x: (priority.get(x.get("action"), 99), -(x.get("market_price") or 0)))

    return out[:limit]


@app.get("/api/titles")
def list_titles():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT DISTINCT TRIM(title) AS title
        FROM comics
        WHERE status IN ('unlisted','drafted')
          AND sold_price IS NULL
          AND title IS NOT NULL
          AND TRIM(title) <> ''
        ORDER BY title COLLATE NOCASE ASC
        """
    ).fetchall()
    conn.close()
    return [r["title"] for r in rows]


@app.get("/api/comics/{comic_id}/evidence")
def comic_evidence(comic_id: int):
    conn = get_conn()
    comic = conn.execute(
        """
        SELECT c.id, c.title, c.issue, c.marvel_id, c.grade_numeric, c.qualified_flag,
               ps.universal_market_price, ps.qualified_market_price, ps.market_price, ps.active_anchor_price,
               ps.confidence, ps.basis_count
        FROM comics c
        LEFT JOIN price_suggestions ps ON ps.comic_id = c.id
        WHERE c.id = ?
        """,
        (comic_id,),
    ).fetchone()
    if not comic:
        conn.close()
        return {"error": "not_found", "comic_id": comic_id}

    sold_rows = conn.execute(
        """
        SELECT
          pse.rank,
          mc.id AS comp_id,
          mc.title,
          mc.issue,
          mc.price,
          mc.shipping,
          mc.sold_date,
          mc.grade_numeric,
          mc.grade_company,
          mc.is_raw,
          mc.is_signed,
          mc.match_score,
          mc.url,
          mc.listing_type
        FROM price_suggestion_evidence pse
        JOIN market_comps mc ON mc.id = pse.comp_id
        WHERE pse.comic_id = ? AND mc.listing_type = 'sold'
        ORDER BY pse.rank ASC
        """,
        (comic_id,),
    ).fetchall()

    active_rows = conn.execute(
        """
        WITH ranked AS (
          SELECT
            mc.id AS comp_id,
            mc.title,
            mc.issue,
            mc.price,
            mc.shipping,
            mc.sold_date,
            mc.grade_numeric,
            mc.grade_company,
            mc.is_raw,
            mc.is_signed,
            mc.match_score,
            mc.url,
            mc.listing_type,
            ROW_NUMBER() OVER (
              PARTITION BY
                LOWER(TRIM(COALESCE(mc.title, ''))),
                ROUND(COALESCE(mc.price, 0), 2),
                COALESCE(mc.grade_numeric, -1),
                LOWER(TRIM(COALESCE(mc.grade_company, ''))),
                COALESCE(mc.is_raw, 0)
              ORDER BY COALESCE(mc.match_score,0) DESC, mc.id DESC
            ) AS rn
          FROM market_comps mc
          WHERE mc.comic_id = ?
            AND mc.listing_type = 'active'
        )
        SELECT comp_id, title, issue, price, shipping, sold_date, grade_numeric,
               grade_company, is_raw, is_signed, match_score, url, listing_type
        FROM ranked
        WHERE rn = 1
        ORDER BY COALESCE(match_score,0) DESC, comp_id DESC
        LIMIT 40
        """,
        (comic_id,),
    ).fetchall()

    conn.close()

    return {
        "comic": dict(comic),
        "sold_count": len(sold_rows),
        "active_count": len(active_rows),
        "sold_evidence": [dict(r) for r in sold_rows],
        "active_evidence": [dict(r) for r in active_rows],
    }


@app.get("/comics/{comic_id}/evidence", response_class=HTMLResponse)
def comic_evidence_page(comic_id: int):
    payload = comic_evidence(comic_id)
    if payload.get("error") == "not_found":
        return HTMLResponse(f"<h2>Comic {comic_id} not found</h2>", status_code=404)

    c = payload["comic"]
    priced = dict(c)
    priced.update(decision_for_row(priced, DEFAULTS))
    sold_evidence = payload.get("sold_evidence", [])
    active_evidence = payload.get("active_evidence", [])
    photos = photo_candidates(c.get("title"), c.get("issue"), c.get("marvel_id"))
    importance = issue_importance_text(c.get("title"), c.get("issue"), c.get("marvel_id"))

    def fmt_money(v):
        return "" if v is None else f"${float(v):,.2f}"

    def yn(v):
        return "Yes" if v else ""

    def comp_is_raw(e):
        t = (e.get("title") or "").lower()
        gc = (e.get("grade_company") or "").lower()

        # User rule: only CGC-tagged books are slabbed; otherwise treat as raw.
        if "cgc" in t or "cgc" in gc:
            return False
        return True

    def render_chart(points, this_grade, this_price, color, title, table_name):
        w, h, pad = 520, 220, 28
        raw_dot_color = "#dc2626"   # red
        slab_dot_color = "#2563eb"  # blue
        raw_line_color = "#b91c1c"
        slab_line_color = "#1d4ed8"

        pts = [
            {
                "grade": float(p.get("grade_numeric")),
                "price": float(p.get("price")),
                "comp_id": p.get("comp_id"),
                "title": p.get("title") or "",
                "is_raw": comp_is_raw(p),
            }
            for p in points
            if p.get("grade_numeric") is not None and p.get("price") is not None
        ]
        if not pts:
            return f"<div class='muted'>{title}: not enough graded points.</div>"
        xs = [p["grade"] for p in pts]
        ys = [p["price"] for p in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x0 == x1:
            x0 -= 0.5
            x1 += 0.5
        if y0 == y1:
            y0 = 0
            y1 += 1

        def sx(x):
            return pad + (x - x0) * ((w - 2 * pad) / (x1 - x0))

        def sy(y):
            return h - pad - (y - y0) * ((h - 2 * pad) / (y1 - y0))

        grid_lines = ""
        start = int(math.ceil(y0 / 100.0) * 100)
        end = int(math.floor(y1 / 100.0) * 100)
        if end >= start:
            for gy in range(start, end + 1, 100):
                ypix = sy(float(gy))
                grid_lines += (
                    f"<line x1='{pad}' y1='{ypix:.1f}' x2='{w-pad}' y2='{ypix:.1f}' stroke='#e5e7eb' stroke-width='1'/>"
                    f"<text x='{pad+4}' y='{ypix-2:.1f}' font-size='10' fill='#9ca3af'>${gy}</text>"
                )

        circles = ""
        for p in pts:
            cx = sx(p["grade"])
            cy = sy(p["price"])
            dot_color = raw_dot_color if p["is_raw"] else slab_dot_color
            raw_label = "RAW" if p["is_raw"] else "SLABBED/UNSPECIFIED"
            title_text = escape(f"{raw_label} • Grade {p['grade']:.1f} • ${p['price']:.2f} • {p['title'][:120]}")
            circles += (
                f"<circle class='chart-dot' data-table='{table_name}' data-comp-id='{p['comp_id']}' "
                f"data-tip='{title_text}' "
                f"cx='{cx:.1f}' cy='{cy:.1f}' r='5.5' fill='{dot_color}' opacity='0.9' style='cursor:pointer;'>"
                f"<title>{title_text}</title></circle>"
            )

        def _series(group_pts):
            by_grade = {}
            for p in group_pts:
                g = float(p["grade"])
                by_grade.setdefault(g, []).append(float(p["price"]))
            out = [(g, sorted(v)[len(v)//2]) for g, v in by_grade.items() if v]
            out.sort(key=lambda t: t[0])
            return out

        def _interp_price(series, g):
            if not series:
                return None
            if len(series) == 1:
                return series[0][1]
            x = float(g)
            if x <= series[0][0]:
                return series[0][1]
            if x >= series[-1][0]:
                return series[-1][1]
            for i in range(len(series)-1):
                x0s, y0s = series[i]
                x1s, y1s = series[i+1]
                if x0s <= x <= x1s:
                    t = (x - x0s) / (x1s - x0s)
                    if y0s > 0 and y1s > 0:
                        return math.exp(math.log(y0s) + t * (math.log(y1s) - math.log(y0s)))
                    return y0s + t * (y1s - y0s)
            return None

        def trend_line_for(group_pts, stroke):
            series = _series(group_pts)
            if len(series) < 2:
                return "", None
            # Smoothly connect dots with quadratic segments through grade-ordered medians.
            pts_xy = [(sx(g), sy(p)) for g, p in series]
            d = f"M {pts_xy[0][0]:.1f} {pts_xy[0][1]:.1f}"
            for i in range(1, len(pts_xy)):
                x_prev, y_prev = pts_xy[i-1]
                x_cur, y_cur = pts_xy[i]
                cx = (x_prev + x_cur) / 2
                cy = (y_prev + y_cur) / 2
                d += f" Q {x_prev:.1f} {y_prev:.1f} {cx:.1f} {cy:.1f}"
            d += f" T {pts_xy[-1][0]:.1f} {pts_xy[-1][1]:.1f}"
            est = _interp_price(series, this_grade) if this_grade is not None else None
            return f"<path d='{d}' fill='none' stroke='{stroke}' stroke-width='2' opacity='0.95'/>", est

        raw_pts = [p for p in pts if p["is_raw"]]
        slab_pts = [p for p in pts if not p["is_raw"]]
        raw_trend_line, raw_est = trend_line_for(raw_pts, raw_line_color)
        slab_trend_line, slab_est = trend_line_for(slab_pts, slab_line_color)

        this_dot = ""
        if this_grade is not None:
            est_price = slab_est if slab_est is not None else raw_est
            dot_price = est_price if est_price is not None else this_price
            if dot_price is not None:
                this_dot = f"<circle cx='{sx(float(this_grade)):.1f}' cy='{sy(float(dot_price)):.1f}' r='5' fill='#111' />"

        return f"""
        <div class='chart-card'>
          <div style='font-weight:600; margin-bottom:4px;'>{title}</div>
          <svg viewBox='0 0 {w} {h}' width='100%' height='220'>
            <rect x='0' y='0' width='{w}' height='{h}' fill='#fff'/>
            <line x1='{pad}' y1='{h-pad}' x2='{w-pad}' y2='{h-pad}' stroke='#bbb'/>
            <line x1='{pad}' y1='{pad}' x2='{pad}' y2='{h-pad}' stroke='#bbb'/>
            {grid_lines}
            {slab_trend_line}
            {raw_trend_line}
            {circles}
            {this_dot}
            <text x='{w/2:.0f}' y='{h-4}' font-size='11' text-anchor='middle' fill='#555'>Grade</text>
            <text x='10' y='{h/2:.0f}' font-size='11' fill='#555' transform='rotate(-90 10,{h/2:.0f})' text-anchor='middle'>Price</text>
          </svg>
          <div class='muted'>Hover dots for price. Red dots/line = RAW. Blue/amber dots/line = slabbed/unspecified. Click a dot to highlight its matching eBay row.</div>
        </div>
        """

    sold_rows_html = ""
    for e in sold_evidence:
        total = (e.get("price") or 0) + (e.get("shipping") or 0)
        title = escape(e.get("title") or "")
        url = escape(e.get("url") or "")
        sold_date = escape(e.get("sold_date") or "")
        grade_company = escape(e.get("grade_company") or "")
        score = "" if e.get("match_score") is None else f"{float(e.get('match_score')):.2f}"
        sold_rows_html += f"""
        <tr id='sold-row-{e.get('comp_id')}' data-comp-id='{e.get('comp_id')}'>
          <td>{e.get('rank') or ''}</td>
          <td>{title}</td>
          <td>{fmt_money(e.get('price'))}</td>
          <td>{fmt_money(e.get('shipping'))}</td>
          <td>{fmt_money(total)}</td>
          <td>{sold_date}</td>
          <td>{e.get('grade_numeric') or ''}</td>
          <td>{grade_company}</td>
          <td>{yn(comp_is_raw(e))}</td>
          <td>{yn(e.get('is_signed'))}</td>
          <td>{score}</td>
          <td>{f'<a href="{url}" target="_blank" rel="noopener">View listing</a>' if url else ''}</td>
        </tr>
        """

    if not sold_rows_html:
        sold_rows_html = "<tr><td colspan='12'>No sold evidence rows yet for this comic.</td></tr>"

    active_rows_html = ""
    for e in active_evidence:
        total = (e.get("price") or 0) + (e.get("shipping") or 0)
        title = escape(e.get("title") or "")
        url = escape(e.get("url") or "")
        sold_date = escape(e.get("sold_date") or "")
        grade_company = escape(e.get("grade_company") or "")
        score = "" if e.get("match_score") is None else f"{float(e.get('match_score')):.2f}"
        active_rows_html += f"""
        <tr id='active-row-{e.get('comp_id')}' data-comp-id='{e.get('comp_id')}'>
          <td>{title}</td>
          <td>{fmt_money(e.get('price'))}</td>
          <td>{fmt_money(e.get('shipping'))}</td>
          <td>{fmt_money(total)}</td>
          <td>{sold_date}</td>
          <td>{e.get('grade_numeric') or ''}</td>
          <td>{grade_company}</td>
          <td>{yn(comp_is_raw(e))}</td>
          <td>{yn(e.get('is_signed'))}</td>
          <td>{score}</td>
          <td>{f'<a href="{url}" target="_blank" rel="noopener">View listing</a>' if url else ''}</td>
        </tr>
        """
    if not active_rows_html:
        active_rows_html = "<tr><td colspan='11'>No active/offer rows yet.</td></tr>"

    sold_chart = render_chart(sold_evidence, c.get("grade_numeric"), c.get("market_price"), "#1d4ed8", "Sold comps curve", "sold")
    active_chart = render_chart(active_evidence, c.get("grade_numeric"), c.get("active_anchor_price"), "#b45309", "Active/offer curve", "active")

    return f"""
    <html><head><title>FMV Evidence - {escape(c.get('title') or '')} #{escape(str(c.get('issue') or ''))}</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; }}
      .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
      .muted {{ color:#666; }}
      table {{ border-collapse: collapse; width:100%; }}
      th, td {{ border:1px solid #ddd; padding:8px; text-align:left; font-size:14px; }}
      th {{ background:#f5f5f5; position: sticky; top: 0; }}
      .meta {{ display:flex; gap:18px; flex-wrap:wrap; margin: 8px 0 14px; }}
      .pill {{ border:1px solid #ddd; border-radius:999px; padding:4px 10px; background:#fafafa; }}
      .photos {{ display:flex; gap:10px; flex-wrap:wrap; margin:10px 0 14px; }}
      .photos img {{ width:120px; height:160px; object-fit:cover; border:1px solid #ddd; border-radius:8px; background:#fff; }}
      .charts {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin: 10px 0 14px; }}
      .chart-card {{ border:1px solid #ddd; border-radius:8px; padding:8px; background:#fff; }}
      .chart-dot.active {{ stroke:#111; stroke-width:2.5; }}
      .dot-tip {{ position: fixed; z-index: 99999; pointer-events: none; max-width: 420px; background: rgba(17,24,39,.96); color: #fff; border:1px solid rgba(255,255,255,.25); border-radius:10px; padding:10px 12px; font-size:14px; line-height:1.35; box-shadow:0 8px 24px rgba(0,0,0,.25); display:none; }}
      tr.comp-highlight {{ background:#fff7d6 !important; }}
      a {{ color:#0b57d0; }}
    </style></head><body>
      <div class='top'>
        <h2>FMV Evidence</h2>
        <a href='/'>← Back to dashboard</a>
      </div>
      <div class='meta'>
        <div class='pill'><b>Comic:</b> {escape(c.get('title') or '')} #{escape(str(c.get('issue') or ''))}</div>
        <div class='pill'><b>Comic ID:</b> {c.get('id')}</div>
        <div class='pill'><b>Your Grade:</b> {c.get('grade_numeric') or ''}</div>
        <div class='pill'><b>Universal FMV:</b> {fmt_money(c.get('universal_market_price'))}</div>
        <div class='pill'><b>Qualified FMV:</b> {fmt_money(c.get('qualified_market_price'))}</div>
        <div class='pill'><b>Applied FMV:</b> {fmt_money(c.get('market_price'))}</div>
        <div class='pill'><b>Suggested eBay Ask:</b> {fmt_money(priced.get('target_price'))}</div>
        <div class='pill'><b>Min Accept (floor):</b> {fmt_money(priced.get('floor_price'))}</div>
        <div class='pill'><b>Active Ask Anchor:</b> {fmt_money(c.get('active_anchor_price'))}</div>
        <div class='pill'><b>Sold rows:</b> {payload.get('sold_count', 0)}</div><div class='pill'><b>Active rows:</b> {payload.get('active_count', 0)}</div>
      </div>
      <div class='card-note' style='margin:8px 0 10px; padding:10px; border:1px solid #ddd; border-radius:8px; background:#fff;'><b>Why this issue matters:</b> {escape(importance)}</div>
      <div class='muted' style='margin-bottom:6px;'>All photos found for this comic:</div>
      <div class='photos'>{''.join([f'<a href=\"{escape(u)}\" target=\"_blank\"><img src=\"{escape(u)}\" loading=\"lazy\"></a>' for u in photos]) if photos else '<span class=\"muted\">No local photos matched yet.</span>'}</div>
      <div class='charts'>{sold_chart}{active_chart}</div>
      <div id='dot-tip' class='dot-tip' aria-hidden='true'></div>
      <h3>eBay Sold Evidence</h3>
      <div class='table-wrap'>
      <table>
        <thead>
          <tr><th>#</th><th>Listing title</th><th>Price</th><th>Ship</th><th>Total</th><th>Sold date</th><th>Grade</th><th>Company</th><th>Raw</th><th>Signed</th><th>Score</th><th>Evidence link</th></tr>
        </thead>
        <tbody>
          {sold_rows_html}
        </tbody>
      </table>
      <h3 style='margin-top:14px;'>eBay Active / Offered Evidence</h3>
      <table>
        <thead>
          <tr><th>Listing title</th><th>Ask</th><th>Ship</th><th>Total</th><th>Date</th><th>Grade</th><th>Company</th><th>Raw</th><th>Signed</th><th>Score</th><th>Evidence link</th></tr>
        </thead>
        <tbody>
          {active_rows_html}
        </tbody>
      </table>
      <script>
        (() => {{
          const dots = Array.from(document.querySelectorAll('.chart-dot'));
          function clearHighlight() {{
            document.querySelectorAll('tr.comp-highlight').forEach(r => r.classList.remove('comp-highlight'));
            dots.forEach(d => d.classList.remove('active'));
          }}
          const tip = document.getElementById('dot-tip');
          function showTip(e, dot) {{
            if (!tip) return;
            const txt = dot.getAttribute('data-tip') || '';
            tip.textContent = txt;
            tip.style.display = 'block';
            tip.setAttribute('aria-hidden', 'false');
            const x = (e.clientX || 0) + 14;
            const y = (e.clientY || 0) + 14;
            tip.style.left = `${{x}}px`;
            tip.style.top = `${{y}}px`;
          }}
          function hideTip() {{
            if (!tip) return;
            tip.style.display = 'none';
            tip.setAttribute('aria-hidden', 'true');
          }}

          dots.forEach(dot => {{
            dot.addEventListener('mouseenter', (e) => showTip(e, dot));
            dot.addEventListener('mousemove', (e) => showTip(e, dot));
            dot.addEventListener('mouseleave', hideTip);
            dot.addEventListener('click', () => {{
              clearHighlight();
              dot.classList.add('active');
              const table = dot.getAttribute('data-table');
              const compId = dot.getAttribute('data-comp-id');
              const row = document.getElementById(`${{table}}-row-${{compId}}`);
              if (row) {{
                row.classList.add('comp-highlight');
                row.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
              }}
            }});
          }});
        }})();
      </script>
    </body></html>
    """



@app.get("/comics/{comic_id}/listing", response_class=HTMLResponse)
def comic_listing_page(comic_id: int, channel: str | None = None):
    conn = get_conn()
    row = conn.execute(
        f"""
        SELECT c.id, c.title, c.issue, c.year, c.marvel_id, c.community_url, c.cgc_cert, c.grade_numeric, c.qualified_flag,
               {grade_class_sql()} AS grade_class,
               ps.market_price, ps.universal_market_price, ps.qualified_market_price, ps.active_anchor_price, ps.active_count, ps.confidence, ps.basis_count
        FROM comics c
        LEFT JOIN price_suggestions ps ON ps.comic_id = c.id
        WHERE c.id = ?
        """,
        (comic_id,),
    ).fetchone()
    conn.close()

    if not row:
        return HTMLResponse(f"<h2>Comic {comic_id} not found</h2>", status_code=404)

    d = dict(row)
    d.update(decision_for_row(d, DEFAULTS))
    recommended = d.get("channel_hint") or "ebay"
    channel = (channel or recommended).strip()
    photos = photo_candidates(d.get("title"), d.get("issue"), d.get("marvel_id"))
    importance = issue_importance_text(d.get("title"), d.get("issue"), d.get("marvel_id"))

    def money(v):
        return "" if v is None else f"${float(v):,.2f}"

    title = f"{d.get('title') or ''} #{d.get('issue') or ''}".strip()
    listing_title = title
    if d.get("grade_numeric"):
        listing_title += f" {d.get('grade_numeric')}"
    if d.get("qualified_flag"):
        listing_title += " (Qualified)"

    notes = []
    if d.get("qualified_flag"):
        notes.append("Qualified label noted (detached pin-up/defect details in description).")
    if d.get("confidence"):
        notes.append(f"Comp confidence: {d.get('confidence')}")

    strategy = {
        "ebay_fixed_price_offers": "List fixed-price above FMV, accept offers down to floor.",
        "ebay_or_facebook_groups": "Cross-post to eBay + Facebook groups; first paid buyer wins.",
        "heritage_or_major_auction": "Consider consignment/major auction for top-end price discovery.",
        "ebay": "List fixed-price on eBay with offers enabled.",
    }.get(channel, "List with evidence-backed pricing and controlled negotiation.")

    pgm_line = f"- PleaseGradeMe thread: {d.get('community_url')}\n" if d.get("community_url") else ""

    desc = f"""{title}

Why this issue matters
- {importance}

Grade: {d.get('grade_numeric') or 'N/A'}{' Qualified' if d.get('qualified_flag') else ''}
Universal FMV: {money(d.get('universal_market_price'))}
Qualified FMV: {money(d.get('qualified_market_price'))}
Target FMV used: {money(d.get('market_price'))}
Active ask median: {money(d.get('active_anchor_price'))}

Pricing Plan
- Anchor: {money(d.get('anchor_price'))}
- Target: {money(d.get('target_price'))}
- Floor: {money(d.get('floor_price'))}

Strategy
- {strategy}

Evidence
- Sold comps and links: http://127.0.0.1:8080/comics/{comic_id}/evidence
{pgm_line}"""

    photo_html = ''.join([f'<a href="{escape(u)}" target="_blank"><img src="{escape(u)}" loading="lazy"></a>' for u in photos])

    return f"""
    <html><head><title>Listing Plan - {escape(title)}</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; margin: 24px; background:#f6f8fb; color:#162033; }}
      .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
      .grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:14px; }}
      .card {{ background:#fff; border:1px solid #e4e7ec; border-radius:12px; padding:12px; }}
      .pill {{ display:inline-block; padding:4px 10px; border:1px solid #e4e7ec; border-radius:999px; margin:0 6px 6px 0; background:#fff; }}
      .photos {{ display:flex; gap:10px; flex-wrap:wrap; }}
      .photos img {{ width:130px; height:170px; object-fit:cover; border:1px solid #ddd; border-radius:8px; }}
      textarea {{ width:100%; min-height:260px; border:1px solid #d0d5dd; border-radius:8px; padding:10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
      a {{ color:#1849a9; }}
    </style></head><body>
      <div class='top'>
        <h2>Proposed Listing</h2>
        <div><a href='/'>← Dashboard</a> · <a href='/comics/{comic_id}/evidence' target='evidence_tab'>Evidence</a></div>
      </div>

      <div class='card' style='margin-bottom:12px;'><b>Why this issue matters:</b> {escape(importance)}</div>

      <div style='margin-bottom:8px;'>
        <span class='pill'><b>{escape(title)}</b></span>
        <span class='pill'>Type: {escape(d.get('grade_class') or 'unknown')}</span>
        <span class='pill'>Grade: {escape(str(d.get('grade_numeric') or 'N/A'))}{' Qualified' if d.get('qualified_flag') else ''}</span>
        <span class='pill'>CGC Cert: {escape(d.get('cgc_cert') or '—')}</span>
        <span class='pill'>Channel: {escape(channel)}</span>
        <span class='pill'>Anchor {money(d.get('anchor_price'))}</span>
        <span class='pill'>Target {money(d.get('target_price'))}</span>
        <span class='pill'>Floor {money(d.get('floor_price'))}</span>
      </div>

      <div class='grid'>
        <div class='card'>
          <h3>Photos</h3>
          <div class='photos'>{photo_html if photo_html else '<span>No photos matched yet.</span>'}</div>
        </div>
        <div class='card'>
          <h3>Listing Title</h3>
          <div style='font-weight:600; margin-bottom:8px;'>{escape(listing_title)}</div>
          <h3>Listing Description Draft</h3>
          <textarea>{escape(desc)}</textarea>
          <div style='margin-top:8px;'>
            {'<div>Notes: ' + escape(' '.join(notes)) + '</div>' if notes else ''}
          </div>
        </div>
      </div>
    </body></html>
    """


def _parse_issue_num(issue):
    s = str(issue or "").strip()
    m = re.search(r"\d+", s)
    return str(int(m.group(0))) if m else s


def _api_offer_index():
    """Map (title_lower, issue_num) -> latest offerId from local API ledger."""
    ledger_path = Path(__file__).resolve().parent.parent / "data" / "api_offer_ledger.jsonl"
    out = {}
    if not ledger_path.exists():
        return out
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        title = (r.get("title") or "").lower()
        m = re.search(r"^(.*?)\s*#\s*(\d+)", title)
        if not m:
            continue
        t = m.group(1).strip()
        issue_num = str(int(m.group(2)))
        oid = r.get("offerId")
        if t and issue_num and oid:
            out[(t, issue_num)] = str(oid)
    return out


def _desc_html_to_text(s: str):
    if not s:
        return ""
    t = s
    t = re.sub(r"<\s*br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<\s*/p\s*>", "\n\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = unescape(t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _ebay_api_base():
    env = (os.getenv("EBAY_ENV") or "production").lower()
    return "https://api.ebay.com" if env.startswith("prod") else "https://api.sandbox.ebay.com"


def _ebay_refresh_token():
    cid = os.getenv("EBAY_CLIENT_ID")
    sec = os.getenv("EBAY_CLIENT_SECRET")
    rt = os.getenv("EBAY_REFRESH_TOKEN")
    if not cid or not sec or not rt:
        raise RuntimeError("Missing EBAY_CLIENT_ID/EBAY_CLIENT_SECRET/EBAY_REFRESH_TOKEN in .env")
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    scopes = " ".join([
        "https://api.ebay.com/oauth/api_scope",
        "https://api.ebay.com/oauth/api_scope/sell.inventory",
        "https://api.ebay.com/oauth/api_scope/sell.account",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    ])
    r = requests.post(
        f"{_ebay_api_base()}/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "scope": scopes,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


@app.get("/api-drafts", response_class=HTMLResponse)
def api_drafts_viewer():
    ledger_path = Path(__file__).resolve().parent.parent / "data" / "api_offer_ledger.jsonl"
    rows = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    # newest first and de-dup by offerId/sku
    dedup = {}
    for r in reversed(rows):
        k = r.get("offerId") or r.get("sku")
        if k and k not in dedup:
            dedup[k] = r
    rows = list(dedup.values())

    api_err = None
    token = None
    try:
        token = _ebay_refresh_token()
    except Exception as ex:
        api_err = str(ex)

    details = {}
    if token:
        H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        for r in rows:
            oid = r.get("offerId")
            sku = r.get("sku")
            entry = {"offer": None, "inventory": None, "error": None}
            try:
                if oid:
                    ro = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/offer/{oid}", headers=H, timeout=20)
                    if ro.status_code == 200:
                        entry["offer"] = ro.json()
                    else:
                        entry["error"] = f"offer {ro.status_code}"
                if sku:
                    ri = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, timeout=20)
                    if ri.status_code == 200:
                        entry["inventory"] = ri.json()
                    elif not entry["error"]:
                        entry["error"] = f"inventory {ri.status_code}"
            except Exception as ex:
                entry["error"] = str(ex)
            details[oid or sku or str(len(details))] = entry

    def fmt_ts(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return s or ""

    body_rows = []
    for r in rows:
        oid = r.get("offerId", "")
        sku = r.get("sku", "")
        key = oid or sku
        d = details.get(key, {})
        offer = d.get("offer") or {}
        inv = d.get("inventory") or {}
        image_count = len((inv.get("product") or {}).get("imageUrls") or [])
        status = offer.get("status") or "unknown"
        price = ((offer.get("pricingSummary") or {}).get("price") or {}).get("value") or r.get("price") or ""
        title = ((inv.get("product") or {}).get("title") or r.get("title") or "")
        err = d.get("error") or ""
        view_url = f"/api-drafts/view/{oid}" if oid else ""
        offer_url = f"/api-drafts/offer/{oid}" if oid else ""
        inv_url = f"/api-drafts/inventory/{sku}" if sku else ""
        body_rows.append(f"""
          <tr>
            <td>{escape(fmt_ts(r.get('createdAt','')))}</td>
            <td>{escape(str(oid))}</td>
            <td>{escape(str(sku))}</td>
            <td>{escape(title)}</td>
            <td>{escape(str(price))}</td>
            <td>{escape(status)}</td>
            <td>{image_count}</td>
            <td><a href=\"{view_url}\" target=\"_blank\">view</a></td>
            <td><a href=\"{offer_url}\" target=\"_blank\">offer API</a></td>
            <td><a href=\"{inv_url}\" target=\"_blank\">inventory API</a></td>
            <td>{escape(err)}</td>
          </tr>
        """)

    rows_html = "\n".join(body_rows) if body_rows else "<tr><td colspan='11'>No API draft entries yet. Create one with scripts/ebay_create_draft.py.</td></tr>"

    return f"""
    <html><head><title>API Draft Viewer</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; margin:24px; background:#f8fafc; }}
      .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:12px; margin-bottom:12px; }}
      table {{ width:100%; border-collapse:collapse; background:#fff; }}
      th,td {{ border:1px solid #e5e7eb; padding:8px; font-size:13px; text-align:left; }}
      th {{ background:#f3f4f6; }}
      a {{ color:#1849a9; }}
    </style></head><body>
      <div class='card'><b>API Draft Offer Viewer</b> · <a href='/api-drafts/descriptions'>Review all descriptions</a> · <a href='/'>Dashboard</a></div>
      <div class='card'>
        <div>This view reads <code>data/api_offer_ledger.jsonl</code> and live-fetches offer/inventory details from eBay API.</div>
        <div>API status: {escape('ok' if token else f'error: {api_err or "unknown"}')}</div>
      </div>
      <table>
        <thead><tr><th>Created</th><th>Offer ID</th><th>SKU</th><th>Title</th><th>Price</th><th>Status</th><th>Images</th><th>View</th><th>Offer URL</th><th>Inventory URL</th><th>Error</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </body></html>
    """


@app.get('/api-drafts/image')
def api_draft_image_proxy(url: str):
    src = unquote(url)
    if not (src.startswith('https://i.ebayimg.com/') or src.startswith('http://i.ebayimg.com/')):
        return Response(status_code=400, content=b'bad image url')
    r = requests.get(src, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return Response(status_code=r.status_code, content=r.content)
    ctype = r.headers.get('content-type', 'image/jpeg')
    return Response(content=r.content, media_type=ctype)


@app.get('/api-drafts/view/{offer_id}', response_class=HTMLResponse)
def api_draft_view(offer_id: str):
    token = _ebay_refresh_token()
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    ro = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/offer/{offer_id}", headers=H, timeout=20)
    if ro.status_code != 200:
        return HTMLResponse(f"<h3>Offer {escape(offer_id)} not found</h3><pre>{escape(ro.text[:1000])}</pre>", status_code=ro.status_code)
    offer = ro.json()

    sku = offer.get("sku") or ""
    inv = {}
    if sku:
        ri = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, timeout=20)
        if ri.status_code == 200:
            inv = ri.json()

    title = ((inv.get("product") or {}).get("title") or "")
    desc = ((offer.get("listingDescription") or (inv.get("product") or {}).get("description") or ""))
    desc_text = _desc_html_to_text(desc)
    images = ((inv.get("product") or {}).get("imageUrls") or [])
    price = (((offer.get("pricingSummary") or {}).get("price") or {}).get("value") or "")
    status = offer.get("status") or "unknown"

    img_html = "".join([
        f"<a href='{escape(u)}' target='_blank'><img src='/api-drafts/image?url={quote(u, safe="")}' loading='lazy'></a>"
        for u in images
    ]) or "<i>No images</i>"

    return f"""
    <html><head><title>API Draft {escape(offer_id)}</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; margin:24px; background:#f8fafc; color:#111827; }}
      .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:12px; margin-bottom:12px; }}
      .photos {{ display:flex; flex-wrap:wrap; gap:10px; }}
      .photos img {{ width:140px; height:180px; object-fit:cover; border:1px solid #ddd; border-radius:8px; }}
      pre {{ white-space:pre-wrap; background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:12px; }}
      a {{ color:#1849a9; }}
    </style></head><body>
      <div class='card'><b>API Draft View</b> · <a href='/api-drafts'>Back to API Drafts</a> · <a href='/'>Dashboard</a> · <a href='/api-drafts/edit/{escape(offer_id)}'><button>Edit</button></a></div>
      <div class='card'><b>Offer ID:</b> {escape(offer_id)} · <b>SKU:</b> {escape(sku)} · <b>Status:</b> {escape(status)} · <b>Price:</b> ${escape(str(price))}</div>
      <div class='card'><h3 style='margin:0 0 8px 0;'>{escape(title)}</h3></div>
      <div class='card'><h4 style='margin:0 0 8px 0;'>Description (rendered)</h4><div>{desc}</div></div>
      <div class='card'><h4 style='margin:0 0 8px 0;'>Description (plain text)</h4><pre>{escape(desc_text)}</pre></div>
      <div class='card'><h4 style='margin:0 0 8px 0;'>Photos ({len(images)})</h4><div class='photos'>{img_html}</div></div>
    </body></html>
    """


@app.get('/api-drafts/edit/{offer_id}', response_class=HTMLResponse)
def api_draft_edit_form(offer_id: str):
    token = _ebay_refresh_token()
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Content-Language": "en-US"}

    ro = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/offer/{offer_id}", headers=H, timeout=20)
    if ro.status_code != 200:
        return HTMLResponse(f"<h3>Offer {escape(offer_id)} not found</h3><pre>{escape(ro.text[:1000])}</pre>", status_code=ro.status_code)
    offer = ro.json()
    sku = offer.get("sku") or ""
    ri = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, timeout=20)
    inv = ri.json() if ri.status_code == 200 else {}

    title = (inv.get("product") or {}).get("title") or ""
    desc = offer.get("listingDescription") or (inv.get("product") or {}).get("description") or ""
    desc = _desc_html_to_text(desc)
    price = (((offer.get("pricingSummary") or {}).get("price") or {}).get("value") or "")

    return f"""
    <html><head><title>Edit API Draft {escape(offer_id)}</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; margin:24px; background:#f8fafc; }}
      .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:12px; margin-bottom:12px; }}
      input, textarea {{ width:100%; border:1px solid #d0d5dd; border-radius:8px; padding:8px; font-size:14px; }}
      textarea {{ min-height:220px; }}
      button {{ padding:10px 14px; border:1px solid #cbd5e1; border-radius:8px; background:#fff; cursor:pointer; }}
      a {{ color:#1849a9; }}
    </style></head><body>
      <div class='card'><b>Edit API Draft</b> · <a href='/api-drafts/view/{escape(offer_id)}'>View</a> · <a href='/api-drafts'>Back</a></div>
      <form method='post' action='/api-drafts/edit/{escape(offer_id)}'>
        <div class='card'><label>Title</label><input name='title' value='{escape(title)}'></div>
        <div class='card'><label>Price (USD)</label><input name='price' value='{escape(str(price))}'></div>
        <div class='card'><label>Description</label><textarea name='description'>{escape(desc)}</textarea></div>
        <button type='submit'>Save changes</button>
      </form>
    </body></html>
    """


@app.post('/api-drafts/edit/{offer_id}')
def api_draft_edit_save(offer_id: str, title: str = Form(...), price: str = Form(...), description: str = Form(...)):
    token = _ebay_refresh_token()
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Content-Language": "en-US"}

    ro = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/offer/{offer_id}", headers=H, timeout=20)
    if ro.status_code != 200:
        return JSONResponse(content={"error": "offer not found", "status": ro.status_code, "body": ro.text[:500]}, status_code=ro.status_code)
    offer = ro.json()
    sku = offer.get("sku") or ""

    ri = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, timeout=20)
    if ri.status_code != 200:
        return JSONResponse(content={"error": "inventory item not found", "status": ri.status_code, "body": ri.text[:500]}, status_code=ri.status_code)
    inv = ri.json()

    qty = (((inv.get("availability") or {}).get("shipToLocationAvailability") or {}).get("quantity") or 1)
    image_urls = ((inv.get("product") or {}).get("imageUrls") or [])

    existing_title = ((inv.get("product") or {}).get("title") or "")
    existing_desc = ((inv.get("product") or {}).get("description") or "")
    inventory_needs_update = (title != existing_title) or (description != existing_desc)

    if inventory_needs_update:
        product_payload = {
            "title": title,
            "description": description,
        }
        if image_urls:
            product_payload["imageUrls"] = image_urls
        inv_payload = {
            "availability": {"shipToLocationAvailability": {"quantity": qty}},
            "product": product_payload,
        }
        pu = requests.put(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, data=json.dumps(inv_payload), timeout=30)
        if pu.status_code >= 300:
            return JSONResponse(content={"error": "inventory update failed", "status": pu.status_code, "body": pu.text[:800]}, status_code=pu.status_code)

    offer["listingDescription"] = description
    offer["pricingSummary"] = {"price": {"value": str(price), "currency": "USD"}}
    po = requests.put(f"{_ebay_api_base()}/sell/inventory/v1/offer/{offer_id}", headers=H, data=json.dumps(offer), timeout=30)
    if po.status_code >= 300:
        return JSONResponse(content={"error": "offer update failed", "status": po.status_code, "body": po.text[:800]}, status_code=po.status_code)

    return RedirectResponse(url=f"/api-drafts/view/{offer_id}", status_code=303)


@app.get('/api-drafts/descriptions', response_class=HTMLResponse)
def api_draft_descriptions():
    ledger_path = Path(__file__).resolve().parent.parent / "data" / "api_offer_ledger.jsonl"
    rows = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    dedup = {}
    for r in reversed(rows):
        k = r.get("offerId")
        if k and k not in dedup:
            dedup[k] = r
    rows = list(dedup.values())

    token = _ebay_refresh_token()
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    out = []
    for r in rows:
        oid = str(r.get("offerId") or "")
        if not oid:
            continue
        ro = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/offer/{oid}", headers=H, timeout=20)
        if ro.status_code != 200:
            continue
        offer = ro.json()
        sku = offer.get("sku") or ""
        title = r.get("title") or ""
        if sku:
            ri = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, timeout=20)
            if ri.status_code == 200:
                title = ((ri.json().get("product") or {}).get("title") or title)
        desc = (offer.get("listingDescription") or "").strip()
        out.append((oid, sku, title, desc))

    rows_html = "".join(
        f"""
        <tr>
          <td><a href='/api-drafts/view/{escape(oid)}' target='_blank'>{escape(oid)}</a></td>
          <td>{escape(sku)}</td>
          <td>{escape(title)}</td>
          <td><pre>{escape(_desc_html_to_text(desc))}</pre></td>
          <td><a href='/api-drafts/edit/{escape(oid)}' target='_blank'>edit</a></td>
        </tr>
        """
        for oid, sku, title, desc in out
    ) or "<tr><td colspan='5'>No API draft descriptions found.</td></tr>"

    return f"""
    <html><head><title>API Draft Descriptions</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; margin: 24px; background:#f8fafc; }}
      .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:12px; margin-bottom:12px; }}
      table {{ width:100%; border-collapse:collapse; background:#fff; }}
      th, td {{ border:1px solid #e5e7eb; padding:8px; vertical-align:top; font-size:13px; }}
      th {{ background:#f3f4f6; position: sticky; top: 0; }}
      pre {{ margin:0; white-space:pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }}
      a {{ color:#1849a9; }}
    </style></head><body>
      <div class='card'><b>API Draft Descriptions</b> · <a href='/api-drafts'>Back to API Drafts</a> · <a href='/'>Dashboard</a></div>
      <table>
        <thead><tr><th>Offer</th><th>SKU</th><th>Title</th><th>Description</th><th>Edit</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </body></html>
    """


@app.get('/api-drafts/offer/{offer_id}', response_class=JSONResponse)
def api_draft_offer_proxy(offer_id: str):
    token = _ebay_refresh_token()
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/offer/{offer_id}", headers=H, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"status": r.status_code, "text": r.text[:500]}
    return JSONResponse(content=data, status_code=r.status_code)


@app.get('/favicon.ico')
def favicon():
    return Response(status_code=204)


@app.get('/api-drafts/inventory/{sku}', response_class=JSONResponse)
def api_draft_inventory_proxy(sku: str):
    token = _ebay_refresh_token()
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.get(f"{_ebay_api_base()}/sell/inventory/v1/inventory_item/{sku}", headers=H, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"status": r.status_code, "text": r.text[:500]}
    return JSONResponse(content=data, status_code=r.status_code)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) AS n FROM comics").fetchone()["n"]
    sold_count = conn.execute("SELECT COUNT(*) AS n FROM comics WHERE status='sold'").fetchone()["n"]
    conn.close()

    decisions = decision_queue(limit=1000)
    counts = {}
    for d in decisions:
        counts[d.get("action")] = counts.get(d.get("action"), 0) + 1

    def card(action_key, label):
        return f"<button class='card-btn' onclick=\"applyActionPreset('{action_key}')\"><b>{label}:</b> {counts.get(action_key,0)}</button>"

    return f"""
    <html><head><title>Comics Sales MVP</title>
    <style>
      :root {{
        --bg: #f6f8fb;
        --panel: #ffffff;
        --text: #162033;
        --muted: #667085;
        --line: #e4e7ec;
        --accent: #2563eb;
      }}
      body {{ font-family: Inter, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; background: var(--bg); color: var(--text); }}
      h1 {{ margin-bottom: 14px; }}
      .stats {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }}
      .card, .card-btn {{ border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:var(--panel); box-shadow: 0 1px 2px rgba(16,24,40,.05); }}
      .card-btn {{ cursor:pointer; transition:.15s ease; }}
      .card-btn:hover {{ border-color:#bfc7d6; transform: translateY(-1px); }}
      .controls {{ display:flex; gap:10px; flex-wrap:wrap; margin: 8px 0 14px; align-items:center; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px; }}
      .controls .apply-btn {{ margin-left:auto; }}
      .filter-wrap .apply-btn {{ justify-self:end; align-self:end; }}
      .filter-actions {{ grid-column: span 2; display:flex; gap:8px; justify-content:flex-end; align-items:end; }}
      .saved-searches {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px; margin:0 0 10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
      .saved-searches .chips {{ display:flex; gap:8px; flex-wrap:wrap; }}
      .chip-btn {{ border-radius:999px; padding:6px 10px; font-size:12px; }}
      .btn-primary {{ background:#1849a9; color:#fff; border-color:#1849a9; font-weight:600; }}
      .btn-primary:hover {{ background:#123a87; border-color:#123a87; }}
      .btn-ghost {{ background:#fff; color:#344054; }}
      .preset-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px; margin: 0 0 10px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
      .filter-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px; margin: 0 0 10px; display:grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); gap:12px; align-items:end; }}
      .filter-wrap label {{ display:flex; flex-direction:column; gap:6px; font-size:12px; color:var(--muted); }}
      .filter-wrap input, .filter-wrap select {{ height:38px; border:1px solid #d0d5dd; border-radius:10px; padding:8px 10px; background:#fff; font-size:14px; color:var(--text); }}
      .filter-wrap input:focus, .filter-wrap select:focus {{ outline:none; border-color:#84a9ff; box-shadow:0 0 0 3px rgba(37,99,235,.16); }}
      .filter-wrap select {{ appearance:none; background-image: linear-gradient(45deg, transparent 50%, #667085 50%), linear-gradient(135deg, #667085 50%, transparent 50%); background-position: calc(100% - 16px) calc(50% - 3px), calc(100% - 10px) calc(50% - 3px); background-size:6px 6px, 6px 6px; background-repeat:no-repeat; padding-right:28px; }}
      .shortcut-group {{ grid-column: span 2; display:flex; gap:8px; align-items:center; flex-wrap:nowrap; overflow-x:auto; }}
      .check-inline {{ display:inline-flex; align-items:center; gap:6px; white-space:nowrap; margin:0; padding:4px 8px; border:1px solid var(--line); border-radius:999px; background:#fff; color:#344054; font-size:12px; line-height:1; }}
      .check-inline input[type='checkbox'] {{ margin:0; width:14px; height:14px; }}
      @media (max-width: 1100px) {{ .filter-wrap {{ grid-template-columns: repeat(3, minmax(120px, 1fr)); }} .shortcut-group {{ grid-column: span 3; }} .filter-actions {{ grid-column: span 3; justify-content:flex-start; }} }}
      .preset-btn {{ border:1px solid var(--line); border-radius:999px; padding:7px 12px; background:#fff; cursor:pointer; font-weight:600; }}
      .preset-btn.active {{ background:#1849a9; color:#fff; border-color:#1849a9; }}
      .preset-btn:hover {{ border-color:#bfc7d6; }}
      label {{ font-size: 12px; color: var(--muted); }}
      input {{ width: 90px; border:1px solid var(--line); border-radius:8px; padding:6px 8px; }}
      button {{ border:1px solid var(--line); border-radius:8px; padding:8px 12px; background:#fff; cursor:pointer; }}
      button:hover {{ border-color:#bfc7d6; }}
      .table-wrap {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:auto; box-shadow: 0 1px 2px rgba(16,24,40,.05); -webkit-overflow-scrolling: touch; max-height:65vh; scrollbar-gutter: stable both-edges; }}
      .scroll-controls {{ margin:0 0 8px; display:flex; gap:8px; position: sticky; top: 0; z-index: 3; background: var(--bg); padding:4px 0; }}
      table {{ border-collapse: separate; border-spacing:0; width:100%; min-width: 980px; }}
      th, td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; font-size: 13px; }}
      th {{ background:#f8fafc; position: sticky; top: 0; z-index: 1; white-space: nowrap; }}
      td:nth-child(2) a {{ display:inline-block; max-width: 220px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .thumb-cell {{ position: relative; overflow: visible; }}
      .thumb-img {{ width:44px; height:58px; object-fit:cover; border:1px solid #d0d5dd; border-radius:6px; background:#fff; cursor: zoom-in; }}
      .img-modal {{ position: fixed; inset: 0; background: rgba(0,0,0,.75); display: none; align-items: center; justify-content: center; z-index: 9999; padding: 20px; }}
      .img-modal.open {{ display: flex; }}
      .img-modal img {{ max-width: 96vw; max-height: 92vh; width: auto; height: auto; border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,.45); cursor: zoom-out; }}
      tbody tr:nth-child(even) {{ background:#fbfcff; }}
      tbody tr:hover {{ background:#f3f7ff; }}
      .muted {{ color:var(--muted); font-size: 13px; }}
      .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid var(--line); background:#fff; font-size:12px; }}
      .badge-action {{ background:#eef4ff; border-color:#cfe0ff; color:#1849a9; font-weight:600; }}
      .badge-yes {{ background:#ecfdf3; border-color:#c6f6d5; color:#027a48; font-weight:600; }}
      a {{ color:#1849a9; text-decoration:none; }}
      a:hover {{ text-decoration:underline; }}
      .sort {{ font-size:11px; margin-left:4px; color:#98a2b3; }}
    </style></head><body>
      <h1 style='margin:0;'>Comics Sales Decision Dashboard</h1>
      <div class='stats' style='margin-top:8px; margin-bottom:8px;'>
        <div class='card'><b>Total:</b> {total}</div>
        <div class='card'><b>Sold:</b> {sold_count}</div>
        {card('list_now_slabbed','List now (slabbed)')}
        {card('slab_candidate','Slab candidates')}
        {card('sell_raw_now','Sell raw now')}
      </div>

      <details class='card' style='margin: 0 0 10px;'>
        <summary style='cursor:pointer; font-weight:600;'>More controls</summary>
        <div style='margin-top:10px;'>
      <div style='margin-bottom:10px; display:flex; gap:8px; align-items:center;'>
        <a href='/api-drafts'><button type='button'>View API Drafts</button></a>
        <span class='muted'>Open offer drafts created via eBay API</span>
      </div>

      <div class='preset-wrap'>
        <button id='preset-selling' class='preset-btn active' type='button' onclick="setClassPreset('selling')">Slabbed + Raw Community</button>
        <button id='preset-raw-only' class='preset-btn' type='button' onclick="setClassPreset('raw_only')">Raw No Community</button>
        <button id='preset-all' class='preset-btn' type='button' onclick="setClassPreset('all')">All Classes</button>
      </div>

      <div class='filter-wrap'>
        <label>Exact column<br>
          <select id='exact_col' onchange='refreshExactValueOptions()'>
            <option value=''>-- none --</option>
            <option value='title'>title</option>
            <option value='issue'>issue</option>
            <option value='grade_class'>class</option>
            <option value='action'>action</option>
            <option value='channel_hint'>channel</option>
            <option value='trend'>trend</option>
          </select>
        </label>
        <label>Exact value<br>
          <input id='exact_val' list='exact_values' type='text' style='width:180px' placeholder='e.g. slabbed,raw_community'>
          <datalist id='exact_values'></datalist>
        </label>
        <label>Title list<br>
          <select id='title_pick' onchange='applyTitlePick()' style='width:220px'>
            <option value=''>-- all titles --</option>
          </select>
        </label>

        <label>Range column<br>
          <select id='range_col'>
            <option value=''>-- none --</option>
            <option value='market_price'>market</option>
            <option value='universal_market_price'>universal_fmv</option>
            <option value='qualified_market_price'>qualified_fmv</option>
            <option value='grade_numeric'>grade</option>
            <option value='net_raw'>net_raw</option>
            <option value='net_slabbed'>net_slabbed</option>
            <option value='slab_lift'>slab_lift</option>
            <option value='slab_lift_pct'>lift_pct</option>
            <option value='anchor_price'>anchor</option>
            <option value='target_price'>target</option>
            <option value='floor_price'>floor</option>
            <option value='trend_pct'>trend_pct</option>
          </select>
        </label>
        <label>Min<br><input id='range_min' type='number' step='0.01' placeholder='min'></label>
        <label>Max<br><input id='range_max' type='number' step='0.01' placeholder='max'></label>
        <label>Limit<br><input id='limit' type='number' step='50' value='500'></label>
        <div class='shortcut-group'>
          <label class='check-inline'><input type='checkbox' id='shortcut_ready_over_100' onchange='applyReadyShortcut("over")'> Ready-to-post + over $100</label>
          <label class='check-inline'><input type='checkbox' id='shortcut_ready_under_100' onchange='applyReadyShortcut("under")'> Ready-to-post + $100 and under</label>
        </div>
        <div class='filter-actions'>
          <button type='button' class='btn-ghost' onclick='clearSelections()'>Clear selection</button>
          <button type='button' class='btn-primary' onclick='reloadCurrent()'>Recalculate</button>
        </div>
      </div>

      <div class='muted'>Click an action bucket above to open that list.</div>
        </div>
      </details>

      <h2 id='section-title'>Decision Queue</h2>
      <div class='saved-searches'>
        <button type='button' class='btn-primary' onclick='saveCurrentSearch()'>Save current search</button>
        <span class='muted'>Saved searches:</span>
        <div class='chips' id='saved-search-chips'></div>
      </div>
      <div style='margin:6px 0; display:flex; gap:10px; align-items:center; flex-wrap:wrap;'>
        <div class='muted' id='selection-summary'>Selection FMV total: $0.00 · 0 books</div>
      </div>
      <div class='muted' style='margin:6px 0;'>Tip: use Shift+mouse-wheel or the buttons to scroll horizontally.</div>
      <div class='scroll-controls'>
        <button type='button' onclick="scrollTable(-500)">← columns</button>
        <button type='button' onclick="scrollTable(500)">columns →</button>
      </div>
      <div id='img-modal' class='img-modal' onclick='closeImageModal()'>
        <img id='img-modal-src' src='' alt='preview' onclick='closeImageModal()'>
      </div>
      <div id='table-wrap' class='table-wrap'>
      <table>
        <thead><tr><th>Photo</th><th>Title <a class='sort' href="#" onclick="setSort('title','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('title','desc');return false;">▼</a></th><th>Issue <a class='sort' href="#" onclick="setSort('issue','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('issue','desc');return false;">▼</a></th><th>Evidence</th><th>Listing</th><th>Ebay</th><th>Class <a class='sort' href="#" onclick="setSort('grade_class','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('grade_class','desc');return false;">▼</a></th><th>Grade <a class='sort' href="#" onclick="setSort('grade_numeric','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('grade_numeric','desc');return false;">▼</a></th><th>Universal FMV <a class='sort' href="#" onclick="setSort('universal_market_price','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('universal_market_price','desc');return false;">▼</a></th><th>Qualified FMV <a class='sort' href="#" onclick="setSort('qualified_market_price','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('qualified_market_price','desc');return false;">▼</a></th><th>Market <a class='sort' href="#" onclick="setSort('market_price','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('market_price','desc');return false;">▼</a></th><th>Ask <a class='sort' href="#" onclick="setSort('target_price','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('target_price','desc');return false;">▼</a></th><th>Net Raw <a class='sort' href="#" onclick="setSort('net_raw','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('net_raw','desc');return false;">▼</a></th><th>Net Slabbed <a class='sort' href="#" onclick="setSort('net_slabbed','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('net_slabbed','desc');return false;">▼</a></th><th>Slab Lift <a class='sort' href="#" onclick="setSort('slab_lift','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('slab_lift','desc');return false;">▼</a></th><th>Lift % <a class='sort' href="#" onclick="setSort('slab_lift_pct','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('slab_lift_pct','desc');return false;">▼</a></th><th>Trend <a class='sort' href="#" onclick="setSort('trend_pct','asc');return false;">▲</a><a class='sort' href="#" onclick="setSort('trend_pct','desc');return false;">▼</a></th><th>Anchor</th><th>Floor</th><th>Qualified</th><th>Action</th></tr></thead>
        <tbody id='rows'><tr><td colspan='22'>Loading...</td></tr></tbody>
      </table>
      </div>
      <div class='scroll-controls' style='position:static; margin-top:8px;'>
        <button type='button' onclick="scrollTable(-500)">← columns</button>
        <button type='button' onclick="scrollTable(500)">columns →</button>
      </div>

      <details class='card' style='margin-top:10px;'>
        <summary style='cursor:pointer; font-weight:600;'>Assumptions (pricing model knobs)</summary>
        <div class='muted' style='margin-top:8px;'>These affect decisions and net values (fees, shipping, slab costs), not which rows are selected.</div>
        <div class='controls' style='margin-top:10px;'>
          <label>Fee %<br><input id='platform_fee_rate' type='number' step='0.01' value='{DEFAULTS['platform_fee_rate']}'></label>
          <label>Ship $<br><input id='avg_ship_cost' type='number' step='1' value='{DEFAULTS['avg_ship_cost']}'></label>
          <label>CGC Grade $<br><input id='cgc_grading_cost' type='number' step='1' value='{DEFAULTS['cgc_grading_cost']}'></label>
          <label>CGC Ship/Ins $<br><input id='cgc_ship_insure_cost' type='number' step='1' value='{DEFAULTS['cgc_ship_insure_cost']}'></label>
          <label>Time penalty %<br><input id='time_penalty_rate' type='number' step='0.01' value='{DEFAULTS['time_penalty_rate']}'></label>
          <label>Min lift $<br><input id='slab_lift_min_dollars' type='number' step='10' value='{DEFAULTS['slab_lift_min_dollars']}'></label>
          <label>Min lift %<br><input id='slab_lift_min_pct' type='number' step='0.01' value='{DEFAULTS['slab_lift_min_pct']}'></label>
          <input id='min_market' type='hidden' value='0'>
          <input type='checkbox' id='gc_slabbed' checked style='display:none'>
          <input type='checkbox' id='gc_raw_community' checked style='display:none'>
          <input type='checkbox' id='gc_raw_no_community' style='display:none'>
        </div>
      </details>

      <script>
        let currentAction = '';
        let currentSortField = 'market_price';
        let currentSortDir = 'desc';
        let lastLoadedData = [];

        function setClassPreset(preset) {{
          const slab = document.getElementById('gc_slabbed');
          const rawCommunity = document.getElementById('gc_raw_community');
          const rawNoCommunity = document.getElementById('gc_raw_no_community');

          document.getElementById('preset-selling').classList.remove('active');
          document.getElementById('preset-raw-only').classList.remove('active');
          document.getElementById('preset-all').classList.remove('active');

          if (preset === 'selling') {{
            slab.checked = true;
            rawCommunity.checked = true;
            rawNoCommunity.checked = false;
            document.getElementById('preset-selling').classList.add('active');
          }} else if (preset === 'raw_only') {{
            slab.checked = false;
            rawCommunity.checked = false;
            rawNoCommunity.checked = true;
            document.getElementById('preset-raw-only').classList.add('active');
          }} else {{
            slab.checked = true;
            rawCommunity.checked = true;
            rawNoCommunity.checked = true;
            document.getElementById('preset-all').classList.add('active');
          }}
          reloadCurrent();
        }}

        function assumptionsParams() {{
          const ids = ['platform_fee_rate','avg_ship_cost','cgc_grading_cost','cgc_ship_insure_cost','time_penalty_rate','slab_lift_min_dollars','slab_lift_min_pct','limit'];
          const p = new URLSearchParams();
          ids.forEach(id => p.set(id, document.getElementById(id).value));
          const minMarketRaw = (document.getElementById('min_market').value || '').trim();
          p.set('min_market', minMarketRaw === '' ? '0' : minMarketRaw);

          const selectedClasses = [];
          if (document.getElementById('gc_slabbed').checked) selectedClasses.push('slabbed');
          if (document.getElementById('gc_raw_community').checked) selectedClasses.push('raw_community');
          if (document.getElementById('gc_raw_no_community').checked) selectedClasses.push('raw_no_community');
          if (selectedClasses.length) p.set('grade_classes', selectedClasses.join(','));

          if (currentAction) p.set('action', currentAction);
          return p;
        }}

        function escAttr(s) {{
          return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        }}

        function refreshExactValueOptions() {{
          const col = document.getElementById('exact_col').value;
          const dl = document.getElementById('exact_values');
          if (!dl) return;
          if (!col) {{
            dl.innerHTML = '';
            return;
          }}
          const vals = new Set();
          for (const r of (lastLoadedData || [])) {{
            const v = r ? r[col] : null;
            if (v === null || v === undefined || v === '') continue;
            vals.add(String(v));
          }}
          const sorted = Array.from(vals).sort((a,b) => a.localeCompare(b, undefined, {{ numeric: true, sensitivity: 'base' }}));
          dl.innerHTML = sorted.map(v => `<option value="${{escAttr(v)}}"></option>`).join('');
        }}

        function applyClientFilters(data) {{
          const exactCol = document.getElementById('exact_col').value;
          const normText = (s) => String(s ?? '')
            .trim()
            .toLowerCase()
            .replace(/[‐‑‒–—]/g, '-');
          const exactVal = normText(document.getElementById('exact_val').value || '');
          const rangeCol = document.getElementById('range_col').value;
          const minRaw = document.getElementById('range_min').value;
          const maxRaw = document.getElementById('range_max').value;
          const hasMin = minRaw !== '';
          const hasMax = maxRaw !== '';
          const minVal = hasMin ? Number(minRaw) : null;
          const maxVal = hasMax ? Number(maxRaw) : null;

          return data.filter(r => {{
            if (exactCol && exactVal) {{
              const v = normText((r[exactCol] ?? '') + '');
              const opts = exactVal.split(',').map(x => normText(x)).filter(Boolean);
              if (opts.length > 0) {{
                if (!opts.includes(v)) return false;
              }} else {{
                if (v !== exactVal) return false;
              }}
            }}

            if (rangeCol && (hasMin || hasMax)) {{
              const v = Number(r[rangeCol]);
              if (Number.isNaN(v)) return false;
              if (hasMin && v < minVal) return false;
              if (hasMax && v > maxVal) return false;
            }}

            return true;
          }});
        }}


        function sortRows(data) {{
          const dir = currentSortDir === 'asc' ? 1 : -1;
          return data.sort((a,b) => {{
            const av = a[currentSortField];
            const bv = b[currentSortField];
            const an = (av === null || av === undefined || av === '') ? Number.NEGATIVE_INFINITY : (isNaN(Number(av)) ? String(av) : Number(av));
            const bn = (bv === null || bv === undefined || bv === '') ? Number.NEGATIVE_INFINITY : (isNaN(Number(bv)) ? String(bv) : Number(bv));
            if (an < bn) return -1 * dir;
            if (an > bn) return 1 * dir;
            return 0;
          }});
        }}

        function setSort(field, dir) {{
          currentSortField = field;
          currentSortDir = dir;
          reloadCurrent();
        }}

        function applyActionPreset(actionKey) {{
          document.getElementById('exact_col').value = 'action';
          document.getElementById('exact_val').value = actionKey || '';
          document.getElementById('section-title').textContent = actionKey ? ('Decision Queue: ' + actionKey) : 'Decision Queue';
          currentAction = '';
          reloadCurrent();
        }}

        function applyReadyShortcut(kind) {{
          const over = document.getElementById('shortcut_ready_over_100');
          const under = document.getElementById('shortcut_ready_under_100');
          if (kind === 'over' && over.checked) under.checked = false;
          if (kind === 'under' && under.checked) over.checked = false;

          if (over.checked || under.checked) {{
            document.getElementById('exact_col').value = 'action';
            document.getElementById('exact_val').value = 'list_now_slabbed,sell_raw_now,slab_candidate';
            document.getElementById('range_col').value = 'market_price';
            if (over.checked) {{
              document.getElementById('range_min').value = '100.01';
              document.getElementById('range_max').value = '';
            }} else {{
              document.getElementById('range_min').value = '0';
              document.getElementById('range_max').value = '100';
            }}
          }}
          reloadCurrent();
        }}

        function clearSelections() {{
          document.getElementById('exact_col').value = '';
          document.getElementById('exact_val').value = '';
          document.getElementById('range_col').value = '';
          document.getElementById('range_min').value = '';
          document.getElementById('range_max').value = '';
          document.getElementById('shortcut_ready_over_100').checked = false;
          document.getElementById('shortcut_ready_under_100').checked = false;
          document.getElementById('title_pick').value = '';
          currentAction = '';
          document.getElementById('section-title').textContent = 'Decision Queue';
          reloadCurrent();
        }}

        function currentSearchState() {{
          return {{
            exact_col: document.getElementById('exact_col').value || '',
            exact_val: document.getElementById('exact_val').value || '',
            range_col: document.getElementById('range_col').value || '',
            range_min: document.getElementById('range_min').value || '',
            range_max: document.getElementById('range_max').value || '',
            title_pick: document.getElementById('title_pick').value || '',
            action: currentAction || '',
            ready_over: !!document.getElementById('shortcut_ready_over_100').checked,
            ready_under: !!document.getElementById('shortcut_ready_under_100').checked,
            gc_slabbed: !!document.getElementById('gc_slabbed').checked,
            gc_raw_community: !!document.getElementById('gc_raw_community').checked,
            gc_raw_no_community: !!document.getElementById('gc_raw_no_community').checked,
            limit: document.getElementById('limit').value || '500',
          }};
        }}

        function applySearchState(s) {{
          document.getElementById('exact_col').value = s.exact_col || '';
          document.getElementById('exact_val').value = s.exact_val || '';
          document.getElementById('range_col').value = s.range_col || '';
          document.getElementById('range_min').value = s.range_min || '';
          document.getElementById('range_max').value = s.range_max || '';
          document.getElementById('title_pick').value = s.title_pick || '';
          currentAction = s.action || '';
          document.getElementById('shortcut_ready_over_100').checked = !!s.ready_over;
          document.getElementById('shortcut_ready_under_100').checked = !!s.ready_under;
          if (typeof s.gc_slabbed !== 'undefined') document.getElementById('gc_slabbed').checked = !!s.gc_slabbed;
          if (typeof s.gc_raw_community !== 'undefined') document.getElementById('gc_raw_community').checked = !!s.gc_raw_community;
          if (typeof s.gc_raw_no_community !== 'undefined') document.getElementById('gc_raw_no_community').checked = !!s.gc_raw_no_community;
          if (typeof s.limit !== 'undefined') document.getElementById('limit').value = s.limit || '500';
          refreshExactValueOptions();
          document.getElementById('section-title').textContent = currentAction ? ('Decision Queue: ' + currentAction) : 'Decision Queue';
          reloadCurrent();
        }}

        function getSavedSearches() {{
          try {{
            return JSON.parse(localStorage.getItem('comics.savedSearches') || '[]');
          }} catch (e) {{
            return [];
          }}
        }}

        function setSavedSearches(items) {{
          localStorage.setItem('comics.savedSearches', JSON.stringify(items));
        }}

        function renderSavedSearches() {{
          const wrap = document.getElementById('saved-search-chips');
          if (!wrap) return;
          const items = getSavedSearches();
          if (!items.length) {{
            wrap.innerHTML = `<span class='muted'>none yet</span>`;
            return;
          }}
          wrap.innerHTML = items.map((x, i) =>
            `<button type='button' class='chip-btn' onclick='runSavedSearch(${{i}})'>${{escAttr(x.name)}}</button>` +
            `<button type='button' class='chip-btn' title='Delete' onclick='deleteSavedSearch(${{i}})'>✕</button>`
          ).join('');
        }}

        function saveCurrentSearch() {{
          const name = prompt('Name this search preset:');
          if (!name) return;
          const items = getSavedSearches();
          items.push({{ name: name.trim(), state: currentSearchState() }});
          setSavedSearches(items);
          renderSavedSearches();
        }}

        function runSavedSearch(i) {{
          const items = getSavedSearches();
          const it = items[i];
          if (!it) return;
          applySearchState(it.state || {{}});
        }}

        function deleteSavedSearch(i) {{
          const items = getSavedSearches();
          items.splice(i, 1);
          setSavedSearches(items);
          renderSavedSearches();
        }}

        function applyTitlePick() {{
          const sel = document.getElementById('title_pick');
          const val = (sel && sel.value) ? sel.value : '';

          // Title picker is authoritative to avoid stale filter combinations.
          currentAction = '';
          document.getElementById('section-title').textContent = 'Decision Queue';
          document.getElementById('shortcut_ready_over_100').checked = false;
          document.getElementById('shortcut_ready_under_100').checked = false;
          document.getElementById('range_col').value = '';
          document.getElementById('range_min').value = '';
          document.getElementById('range_max').value = '';

          if (!val) {{
            document.getElementById('exact_col').value = '';
            document.getElementById('exact_val').value = '';
          }} else {{
            document.getElementById('exact_col').value = 'title';
            document.getElementById('exact_val').value = val;
          }}
          reloadCurrent();
        }}

        async function loadTitleOptions() {{
          const sel = document.getElementById('title_pick');
          if (!sel) return;
          try {{
            const res = await fetch('/api/titles');
            const titles = await res.json();
            if (!Array.isArray(titles)) return;
            const opts = [`<option value=''>-- all titles --</option>`]
              .concat(titles.map(t => `<option value="${{String(t).replace(/"/g, '&quot;')}}">${{t}}</option>`));
            sel.innerHTML = opts.join('');
          }} catch (e) {{
            // no-op
          }}
        }}

        async function loadAction(actionKey) {{
          currentAction = actionKey || '';
          document.getElementById('section-title').textContent = currentAction ? ('Decision Queue: ' + currentAction) : 'Decision Queue';
          const p = assumptionsParams();
          const res = await fetch('/api/decision-queue?' + p.toString());
          let data = await res.json();
          if (!Array.isArray(data)) {{
            const body = document.getElementById('rows');
            body.innerHTML = `<tr><td colspan='22'>API error: ${{JSON.stringify(data)}}</td></tr>`;
            return;
          }}
          lastLoadedData = data.slice();
          refreshExactValueOptions();
          data = applyClientFilters(data);
          data = sortRows(data);
          const totalFmv = data.reduce((acc, r) => acc + (Number(r.market_price || 0) || 0), 0);
          const summary = document.getElementById('selection-summary');
          if (summary) summary.textContent = `Selection FMV total: $${{totalFmv.toFixed(2)}} · ${{data.length}} book${{data.length===1?'':'s'}}`;
          const body = document.getElementById('rows');
          if (!data.length) {{
            body.innerHTML = "<tr><td colspan='22'>No rows</td></tr>";
            return;
          }}
          body.innerHTML = data.map(r => `
            <tr>
              <td class='thumb-cell'>${{r.thumb_url?`<img class='thumb-img' src="${{r.thumb_url}}" onclick="openImageModal('${{r.thumb_url}}')">`:""}}</td>
              <td>${{r.title||''}}</td>
              <td>${{r.issue||''}}</td>
              <td><a class='badge' href="/comics/${{r.id}}/evidence" target="evidence_tab">evidence</a></td>
              <td>${{r.channel_hint?`<a class='badge' href="/comics/${{r.id}}/listing?channel=${{encodeURIComponent(r.channel_hint)}}" target="evidence_tab">listing</a>`:''}}</td>
              <td>${{r.api_offer_id?`<a class='badge' href="/api-drafts/view/${{r.api_offer_id}}" target="_blank">view/edit</a>`:''}}</td>
              <td><span class='badge'>${{r.grade_class||''}}</span></td>
              <td>${{r.grade_numeric??''}}</td>
              <td>${{r.universal_market_price!=null?('$'+Number(r.universal_market_price).toFixed(2)):''}}</td>
              <td>${{(r.qualified_flag && r.qualified_market_price!=null)?('$'+Number(r.qualified_market_price).toFixed(2)):''}}</td>
              <td>${{r.market_price!=null?('$'+Number(r.market_price).toFixed(2)):''}}</td>
              <td><b>${{r.target_price!=null?('$'+Number(r.target_price).toFixed(2)):''}}</b></td>
              <td>${{r.net_raw!=null?('$'+Number(r.net_raw).toFixed(2)):''}}</td>
              <td>${{r.net_slabbed!=null?('$'+Number(r.net_slabbed).toFixed(2)):''}}</td>
              <td>${{r.slab_lift!=null?('$'+Number(r.slab_lift).toFixed(2)):''}}</td>
              <td>${{r.slab_lift_pct!=null?(Number(r.slab_lift_pct).toFixed(1)+'%'):''}}</td>
              <td><span class='badge'>${{r.trend||''}}${{r.trend_pct!=null?(' ('+Number(r.trend_pct).toFixed(1)+'%)'):''}}</span></td>
              <td>${{r.anchor_price!=null?('$'+Number(r.anchor_price).toFixed(2)):''}}</td>
              <td>${{r.floor_price!=null?('$'+Number(r.floor_price).toFixed(2)):''}}</td>
              <td>${{r.qualified_flag ? '<span class="badge badge-yes">Yes</span>' : ''}}</td>
              <td><span class='badge badge-action'>${{r.action||''}}</span></td>
            </tr>
          `).join('');
        }}

        function openImageModal(src) {{
          const modal = document.getElementById('img-modal');
          const img = document.getElementById('img-modal-src');
          if (!modal || !img) return;
          if (modal.classList.contains('open') && img.getAttribute('src') === src) {{
            modal.classList.remove('open');
            img.setAttribute('src', '');
            return;
          }}
          img.setAttribute('src', src);
          modal.classList.add('open');
        }}

        function closeImageModal() {{
          const modal = document.getElementById('img-modal');
          const img = document.getElementById('img-modal-src');
          if (!modal || !img) return;
          modal.classList.remove('open');
          img.setAttribute('src', '');
        }}

        function scrollTable(dx) {{
          const el = document.getElementById('table-wrap');
          if (el) el.scrollBy({{ left: dx, behavior: 'smooth' }});
        }}

        function reloadCurrent() {{ loadAction(currentAction); }}
        loadTitleOptions();
        renderSavedSearches();
        loadAction('');
      </script>
    </body></html>
    """
