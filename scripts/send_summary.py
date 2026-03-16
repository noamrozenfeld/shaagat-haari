#!/usr/bin/env python3
"""
send_summary.py — שולח סיכום אירועים ב-08:00 וב-16:00
"""

import json, os, re, smtplib, ssl
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.request import urlopen, Request
import xml.etree.ElementTree as ET

# ─── CONFIG ────────────────────────────────────────────────────
GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL       = GMAIL_USER  # שולח לעצמך

FEEDS = [
    {"name": "ynet",          "url": "https://www.ynet.co.il/Integration/StoryRss2.xml",  "lang": "he"},
    {"name": "כאן חדשות",     "url": "https://www.kan.org.il/rss/news.aspx",              "lang": "he"},
    {"name": "Times of Israel","url": "https://www.timesofisrael.com/feed/",              "lang": "en"},
]

KEYWORDS_HE = ["טיל","טילים","שיגור","נפילה","פגיעה","יירוט","כטב","שאגת הארי","איראן","אזעקה","רסיס","הרוג","פצוע"]
KEYWORDS_EN = ["missile","rocket","drone","ballistic","iran","attack","intercept","idf","explosion","siren","killed","wounded"]

SEEN_FILE = Path(__file__).parent.parent / "data" / "seen_email.json"

def load_seen() -> set:
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    SEEN_FILE.parent.mkdir(exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-500:], f)

def fetch_rss(url):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            return ET.fromstring(r.read())
    except Exception as e:
        print(f"  ⚠ {url}: {e}")
        return None

def is_relevant(text, lang):
    t = text.lower()
    kws = KEYWORDS_HE if lang == "he" else KEYWORDS_EN
    return any(k.lower() in t for k in kws)

def uid(url):
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]

def build_email_html(items):
    now = datetime.now(timezone(timedelta(hours=3)))
    time_str = now.strftime("%d.%m.%Y %H:%M")
    
    rows = ""
    for item in items:
        title = item["title"]
        link  = item["link"]
        source = item["source"]
        pub   = item["pub"][:16]
        rows += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #eee;">
            <a href="{link}" style="color:#1a73e8;font-weight:bold;text-decoration:none;">{title}</a>
            <br><small style="color:#888;">{source} · {pub}</small>
          </td>
        </tr>"""

    dashboard_url = "https://noamrozenfeld.github.io/shaagat-haari/"

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto;direction:rtl;">
      <div style="background:#0a1520;color:#e85d00;padding:16px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🦁 דשבורד שאגת הארי — עדכון {time_str}</h2>
        <p style="color:#c8dde8;margin:4px 0 0;">{len(items)} כתבות רלוונטיות חדשות</p>
      </div>
      <table style="width:100%;border-collapse:collapse;border:1px solid #ddd;border-top:none;">
        {rows if rows else '<tr><td style="padding:20px;text-align:center;color:#888;">אין כתבות חדשות רלוונטיות</td></tr>'}
      </table>
      <div style="padding:12px;background:#f5f5f5;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
        <a href="{dashboard_url}" style="color:#1a73e8;">🔗 פתח את הדשבורד</a>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        <small style="color:#888;">עדכן את הדשבורד אם יש אירועים חדשים שרלוונטיים</small>
      </div>
    </html></body>"""

def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print(f"✅ Email sent to {TO_EMAIL}")

def main():
    seen = load_seen()
    new_items = []

    for feed in FEEDS:
        print(f"📡 {feed['name']}...")
        root = fetch_rss(feed["url"])
        if not root:
            continue
        for item in root.findall(".//item")[:30]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link")  or "").strip()
            desc  = re.sub(r"<[^>]+>", "", item.findtext("description") or "")
            pub   = (item.findtext("pubDate") or "")[:25]
            text  = title + " " + desc

            article_uid = uid(link)
            if article_uid in seen:
                continue
            if not is_relevant(text, feed["lang"]):
                seen.add(article_uid)
                continue

            new_items.append({
                "title":  title,
                "link":   link,
                "source": feed["name"],
                "pub":    pub,
            })
            seen.add(article_uid)
            print(f"  ✓ {title[:60]}")

    save_seen(seen)

    now = datetime.now(timezone(timedelta(hours=3)))
    hour = now.hour
    period = "בוקר" if hour < 13 else "אחר הצהריים"
    subject = f"🦁 שאגת הארי — עדכון {period} {now.strftime('%d.%m')} | {len(new_items)} כתבות חדשות"

    html = build_email_html(new_items)
    send_email(subject, html)
    print(f"Done — {len(new_items)} new items")

if __name__ == "__main__":
    main()
