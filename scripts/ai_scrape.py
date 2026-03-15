#!/usr/bin/env python3
"""
ai_scrape.py — סקריפט מבוסס Claude API
סורק RSS, שולח כתבות חדשות ל-Claude, ומחלץ אירועים מובנים לעדכון הדשבורד.
"""

import json, os, re, hashlib, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import xml.etree.ElementTree as ET

try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic")
    exit(1)

# ─── CONFIG ────────────────────────────────────────────────────
DATA_DIR    = Path(__file__).parent.parent / "data"
EVENTS_FILE = DATA_DIR / "events.json"
SEEN_FILE   = DATA_DIR / "seen_articles.json"   # מאמרים שכבר עובדו
DATA_DIR.mkdir(exist_ok=True)

# Claude API — המודל הכי זול וטוב לפרסור
MODEL = "claude-haiku-4-5-20251001"

FEEDS = [
    {"name": "ynet",         "url": "https://www.ynet.co.il/Integration/StoryRss2.xml",         "lang": "he"},
    {"name": "כאן חדשות",    "url": "https://www.kan.org.il/rss/news.aspx",                     "lang": "he"},
    {"name": "Times of Israel","url": "https://www.timesofisrael.com/feed/",                    "lang": "en"},
    {"name": "Reuters",       "url": "https://feeds.reuters.com/reuters/topNews",               "lang": "en"},
]

# פילטר ראשוני — כותרות רלוונטיות בלבד
KEYWORDS_HE = ["טיל","טילים","שיגור","נפילה","פגיעה","יירוט","כטב","שאגת הארי","איראן","מתקפה","אזעקה","רסיס"]
KEYWORDS_EN = ["missile","rocket","drone","ballistic","iran","attack","intercept","idf","explosion","siren","shaagat"]

SYSTEM_PROMPT = """אתה מנתח OSINT צבאי. קרא את הכתבה הבאה ובדוק אם היא מדווחת על:
- נפילת טיל / שבר / רסיס בישראל
- פגיעה בנפש (הרוגים / פצועים)
- שיגור טילים מאיראן / לבנון / עיראק
- יירוט של טיל / כטב"מ

אם הכתבה רלוונטית, החזר JSON בלבד (ללא markdown, ללא הסבר) במבנה הבא:
{
  "relevant": true,
  "events": [
    {
      "date": "DD.M",
      "location": "שם המקום בעברית",
      "lat": 32.08,
      "lng": 34.78,
      "type": "hit|frag|intercept|ballistic|uav|cruise",
      "desc": "תיאור קצר בעברית",
      "killed": 0,
      "wounded": 0,
      "source_url": "כתובת המאמר",
      "source_name": "שם המקור"
    }
  ]
}

אם הכתבה לא רלוונטית, החזר: {"relevant": false}

חוקים:
- lat/lng חייבים להיות מדויקים לישראל (lat: 29-34, lng: 34-36)
- אם מקום לא מוכר — השתמש בקואורדינטות של מרכז ישראל (31.5, 34.8)
- type: hit = פגיעה ישירה, frag = שבר/רסיס, intercept = יירוט
- החזר JSON תקני בלבד
"""


def load_seen() -> set:
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def load_events() -> list:
    if EVENTS_FILE.exists():
        with open(EVENTS_FILE) as f:
            return json.load(f).get("events", [])
    return []


def fetch_rss(url: str):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            return ET.fromstring(r.read())
    except Exception as e:
        print(f"  ⚠ RSS error {url}: {e}")
        return None


def is_relevant(text: str, lang: str) -> bool:
    t = text.lower()
    kws = KEYWORDS_HE if lang == "he" else KEYWORDS_EN
    return any(k.lower() in t for k in kws)


def uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def analyze_with_claude(client, article_text: str, article_url: str) -> list:
    """שולח כתבה ל-Claude ומקבל אירועים מובנים"""
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"URL: {article_url}\n\n{article_text[:3000]}"}]
        )
        raw = msg.content[0].text.strip()

        # נקה markdown אם יש
        raw = re.sub(r"```json|```", "", raw).strip()

        parsed = json.loads(raw)
        if not parsed.get("relevant"):
            return []
        return parsed.get("events", [])

    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"  ⚠ Claude API error: {e}")
        return []


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    seen   = load_seen()
    existing_events = load_events()
    existing_ids = {e.get("id","") for e in existing_events}

    new_events = []
    articles_processed = 0

    for feed in FEEDS:
        print(f"\n📡 {feed['name']}...")
        root = fetch_rss(feed["url"])
        if root is None:
            continue

        items = root.findall(".//item")[:20]
        for item in items:
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link")  or "").strip()
            desc    = re.sub(r"<[^>]+>", "", item.findtext("description") or "")
            pub     = (item.findtext("pubDate") or "").strip()
            text    = title + " " + desc

            article_uid = uid(link)

            # דלג אם כבר עיבדנו
            if article_uid in seen:
                continue

            # פילטר ראשוני
            if not is_relevant(text, feed["lang"]):
                seen.add(article_uid)
                continue

            print(f"  🔍 מנתח: {title[:60]}...")
            events = analyze_with_claude(client, f"{title}\n\n{desc}", link)
            seen.add(article_uid)
            articles_processed += 1

            for ev in events:
                ev_id = uid(f"{ev.get('location','')}{ev.get('date','')}{ev.get('desc','')}")
                if ev_id in existing_ids:
                    continue
                ev["id"]  = ev_id
                ev["pub"] = pub
                new_events.append(ev)
                existing_ids.add(ev_id)
                print(f"    ✅ אירוע חדש: {ev.get('location')} — {ev.get('desc','')[:50]}")

            # השהייה קצרה כדי לא להעמיס על ה-API
            time.sleep(0.5)

    # שמור seen
    save_seen(seen)

    # מזג אירועים
    all_events = new_events + existing_events
    all_events = all_events[:500]  # שמור עד 500

    out = {
        "updated":      datetime.now(timezone.utc).isoformat(),
        "total":        len(all_events),
        "new_this_run": len(new_events),
        "articles_processed": articles_processed,
        "events": all_events,
        "stats": {
            "hit":       sum(1 for e in all_events if e.get("type") == "hit"),
            "frag":      sum(1 for e in all_events if e.get("type") == "frag"),
            "intercept": sum(1 for e in all_events if e.get("type") == "intercept"),
            "ballistic": sum(1 for e in all_events if e.get("type") == "ballistic"),
            "uav":       sum(1 for e in all_events if e.get("type") == "uav"),
        }
    }

    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n✅ סיום: {len(new_events)} אירועים חדשים מ-{articles_processed} כתבות")
    print(f"   סה\"כ: {len(all_events)} אירועים | עדכון: {out['updated']}")


if __name__ == "__main__":
    main()
