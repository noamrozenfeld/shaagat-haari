#!/usr/bin/env python3
"""
scrape.py — סורק RSS ומייצר data/events.json
מקורות: ynet, כאן, רויטרס עברית
"""

import json, re, hashlib, os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import xml.etree.ElementTree as ET

# ─── CONFIG ────────────────────────────────────────────────────
OUTPUT = Path(__file__).parent.parent / "data" / "events.json"
OUTPUT.parent.mkdir(exist_ok=True)

FEEDS = [
    {
        "name": "ynet חדשות",
        "url": "https://www.ynet.co.il/Integration/StoryRss2.xml",
        "lang": "he"
    },
    {
        "name": "כאן חדשות",
        "url": "https://www.kan.org.il/rss/news.aspx",
        "lang": "he"
    },
    {
        "name": "Reuters Israel",
        "url": "https://feeds.reuters.com/reuters/topNews",
        "lang": "en"
    },
    {
        "name": "Times of Israel",
        "url": "https://www.timesofisrael.com/feed/",
        "lang": "en"
    },
]

# מילות מפתח לסינון — טילים / מתקפות
KEYWORDS_HE = [
    "טיל", "טילים", "שיגור", "ירי", "רקטה", "כטב״מ", "כטב\"מ",
    "שאגת הארי", "איראן", "אזעקה", "נפילה", "פגיעה", "יירוט",
    "חיזבאללה", "חות'ים", "מבצע", "הגנה", "חץ", "כיפת ברזל"
]
KEYWORDS_EN = [
    "missile", "rocket", "drone", "ballistic", "iran", "attack",
    "intercept", "hezbollah", "houthi", "idf", "israel", "air defense",
    "shaagat", "lion's roar", "explosion", "siren", "projectile"
]

# מיפוי מיקומים לקואורדינטות
LOCATION_MAP = {
    "תל אביב": [32.08, 34.78],
    "ירושלים": [31.78, 35.22],
    "חיפה": [32.82, 34.99],
    "ראשון לציון": [31.97, 34.76],
    "באר שבע": [31.25, 34.79],
    "נתניה": [32.33, 34.86],
    "אשדוד": [31.80, 34.65],
    "אשקלון": [31.67, 34.57],
    "רחובות": [31.90, 34.81],
    "פתח תקווה": [32.09, 34.89],
    "גליל": [32.90, 35.30],
    "גליל עליון": [33.10, 35.50],
    "גליל תחתון": [32.70, 35.30],
    "לוד": [31.96, 34.90],
    "מודיעין": [31.88, 35.01],
    "עכו": [32.93, 35.07],
    "נצרת": [32.70, 35.30],
    "טבריה": [32.79, 35.53],
    "ים המלח": [31.55, 35.48],
    "נגב": [30.80, 34.80],
    "אילת": [29.56, 34.95],
    "tel aviv": [32.08, 34.78],
    "jerusalem": [31.78, 35.22],
    "haifa": [32.82, 34.99],
    "northern israel": [32.90, 35.30],
    "southern israel": [31.00, 34.70],
    "central israel": [32.00, 34.80],
    "negev": [30.80, 34.80],
}

TYPE_KEYWORDS = {
    "ballistic": ["בליסטי", "עימאד", "קדר", "חייבר", "ballistic", "imad", "khorramshahr"],
    "uav":       ["כטב\"מ", "כטב״מ", "שהד", "drone", "uav", "shahed"],
    "cruise":    ["שיוט", "פאווה", "cruise", "ya ali"],
    "intercept": ["יירט", "יירוט", "יורט", "intercept", "iron dome", "arrow", "חץ", "כיפת ברזל"],
    "impact":    ["נפל", "נפילה", "פגיעה", "פצוע", "נהרג", "hit", "impact", "killed", "wounded"],
}


def fetch_rss(url: str) -> ET.Element | None:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            return ET.fromstring(r.read())
    except Exception as e:
        print(f"  ⚠ {url}: {e}")
        return None


def is_relevant(text: str, lang: str) -> bool:
    t = text.lower()
    kws = KEYWORDS_HE if lang == "he" else KEYWORDS_EN
    return any(k.lower() in t for k in kws)


def detect_location(text: str):
    for name, coords in LOCATION_MAP.items():
        if name.lower() in text.lower():
            return {"name": name, "lat": coords[0], "lng": coords[1]}
    return None


def detect_type(text: str) -> str:
    t = text.lower()
    for typ, kws in TYPE_KEYWORDS.items():
        if any(k.lower() in t for k in kws):
            return typ
    return "general"


def uid(title: str) -> str:
    return hashlib.md5(title.encode()).hexdigest()[:10]


def parse_feed(feed_cfg: dict) -> list:
    print(f"  📡 {feed_cfg['name']}...")
    root = fetch_rss(feed_cfg["url"])
    if root is None:
        return []

    items = root.findall(".//item")
    events = []
    for item in items[:40]:
        title = (item.findtext("title") or "").strip()
        desc  = (item.findtext("description") or "").strip()
        link  = (item.findtext("link") or "").strip()
        pub   = (item.findtext("pubDate") or "").strip()
        text  = title + " " + desc

        if not is_relevant(text, feed_cfg["lang"]):
            continue

        # clean HTML tags from description
        desc_clean = re.sub(r"<[^>]+>", "", desc)[:200]

        events.append({
            "id":       uid(title),
            "title":    title,
            "desc":     desc_clean,
            "link":     link,
            "pub":      pub,
            "source":   feed_cfg["name"],
            "type":     detect_type(text),
            "location": detect_location(text),
        })

    print(f"    → {len(events)} רלוונטיים")
    return events


def load_existing() -> list:
    if OUTPUT.exists():
        with open(OUTPUT) as f:
            data = json.load(f)
            return data.get("events", [])
    return []


def merge(existing: list, new: list) -> list:
    seen = {e["id"] for e in existing}
    added = [e for e in new if e["id"] not in seen]
    merged = added + existing
    # שמור רק 200 אירועים אחרונים
    return merged[:200]


def main():
    print("🔍 מתחיל סריקה...")
    all_new = []
    for feed in FEEDS:
        all_new.extend(parse_feed(feed))

    existing = load_existing()
    merged   = merge(existing, all_new)

    out = {
        "updated":     datetime.now(timezone.utc).isoformat(),
        "total":       len(merged),
        "new_this_run": len([e for e in all_new if e["id"] not in {x["id"] for x in existing}]),
        "events":      merged,
        "stats": {
            "ballistic": sum(1 for e in merged if e["type"] == "ballistic"),
            "uav":       sum(1 for e in merged if e["type"] == "uav"),
            "cruise":    sum(1 for e in merged if e["type"] == "cruise"),
            "intercept": sum(1 for e in merged if e["type"] == "intercept"),
            "impact":    sum(1 for e in merged if e["type"] == "impact"),
            "general":   sum(1 for e in merged if e["type"] == "general"),
        }
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"✅ נשמר: {OUTPUT}")
    print(f"   סה\"כ: {out['total']} אירועים, חדשים: {out['new_this_run']}")


if __name__ == "__main__":
    main()
