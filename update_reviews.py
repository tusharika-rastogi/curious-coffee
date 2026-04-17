#!/usr/bin/env python3
"""
update_reviews.py
Fetches Google reviews for Curious Coffee from search results and rebuilds
the reviews section in index.html.

Run manually:  python3 update_reviews.py
Run via CI:    GitHub Actions calls this every Friday at 8pm EST
"""

import re
import sys
import json
import time
import html as html_module
import urllib.request
import urllib.parse
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────
SEARCH_URL  = "https://www.google.com/search?q=Curious+Coffee+Reviews+Ann+Arbor"
INDEX_FILE  = "index.html"
MAX_REVIEWS = 6   # max rev-cards to show

REVIEWS_START = "<!-- REVIEWS_START -->"
REVIEWS_END   = "<!-- REVIEWS_END -->"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── FETCH ──────────────────────────────────────────────────────────────────
def fetch(url, retries=3, delay=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    return None


# ── PARSE REVIEWS ──────────────────────────────────────────────────────────
def extract_from_jsonld(page_html):
    """Try to pull reviews from JSON-LD structured data blocks."""
    reviews = []
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                              page_html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        # Handle single object or @graph array
        items = data if isinstance(data, list) else [data]
        if "@graph" in (data if isinstance(data, dict) else {}):
            items = data["@graph"]

        for item in items:
            if not isinstance(item, dict):
                continue
            for rev in item.get("review", []) + item.get("reviews", []):
                if not isinstance(rev, dict):
                    continue
                body = rev.get("reviewBody") or rev.get("description", "")
                rating = rev.get("reviewRating", {})
                stars = int(float(rating.get("ratingValue", 5)))
                author_info = rev.get("author", {})
                author = author_info.get("name", "Anonymous") if isinstance(author_info, dict) else str(author_info)
                if body:
                    reviews.append({"text": body.strip(), "stars": stars, "author": author.strip()})

    return reviews


def extract_from_html_patterns(page_html):
    """Fallback: grab review snippet text from Google result patterns."""
    reviews = []
    # Google sometimes wraps review snippets in data-ved spans; look for long quoted text
    for m in re.finditer(r'["""]([^"""]{80,400})["""]', html_module.unescape(page_html)):
        text = m.group(1).strip()
        # Skip navigation, boilerplate
        if any(skip in text.lower() for skip in ["privacy", "terms", "cookie", "javascript", "learn more"]):
            continue
        reviews.append({"text": text, "stars": 5, "author": "Google Reviewer"})
        if len(reviews) >= MAX_REVIEWS:
            break
    return reviews


def fetch_reviews():
    print(f"Fetching: {SEARCH_URL}")
    page = fetch(SEARCH_URL)
    if not page:
        print("ERROR: Could not fetch search page.")
        return []

    reviews = extract_from_jsonld(page)
    if reviews:
        print(f"Found {len(reviews)} reviews via JSON-LD structured data.")
        return reviews[:MAX_REVIEWS]

    print("No JSON-LD reviews found, trying HTML pattern extraction...")
    reviews = extract_from_html_patterns(page)
    if reviews:
        print(f"Found {len(reviews)} review snippets via HTML patterns.")
        return reviews[:MAX_REVIEWS]

    print("WARNING: No reviews could be extracted from the page.")
    return []


# ── BUILD HTML ─────────────────────────────────────────────────────────────
DELAY_CLASSES = ["d1", "d2", "d3", "d4", "d1", "d2"]

def stars_html(n):
    return "&#9733;" * max(1, min(5, n))

def build_card(idx, review):
    delay = DELAY_CLASSES[idx % len(DELAY_CLASSES)]
    author = review["author"]
    avatar = author[0].upper() if author else "G"
    text = html_module.escape(review["text"])
    # Wrap in quotes if not already present
    if not text.startswith(("\u201c", "&ldquo;", '"', "\u2018")):
        text = f"\u201c{text}\u201d"
    return f"""\
      <div class="rev-card reveal {delay}">
        <div class="rev-card-stars">{stars_html(review['stars'])}</div>
        <p class="rev-text">{text}</p>
        <div class="rev-author">
          <div class="rev-avatar">{avatar}</div>
          <div>
            <p class="rev-name">{html_module.escape(author)}</p>
            <p class="rev-source">Google Review</p>
          </div>
        </div>
      </div>"""


def build_cards_html(reviews):
    return "\n\n".join(build_card(i, r) for i, r in enumerate(reviews))


# ── INJECT INTO INDEX.HTML ────────────────────────────────────────────────
def update_index(reviews):
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print(f"ERROR: {INDEX_FILE} not found. Run from the repo root.")
        sys.exit(1)

    if REVIEWS_START not in html or REVIEWS_END not in html:
        print(f"ERROR: Markers {REVIEWS_START!r} / {REVIEWS_END!r} not found in {INDEX_FILE}.")
        sys.exit(1)

    cards_html = build_cards_html(reviews)
    start_idx = html.index(REVIEWS_START) + len(REVIEWS_START)
    end_idx   = html.index(REVIEWS_END)
    new_html  = html[:start_idx] + "\n" + cards_html + "\n    " + html[end_idx:]

    # Update timestamp comment if present
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    new_html = re.sub(
        r"<!-- Reviews last updated: .* -->",
        f"<!-- Reviews last updated: {timestamp} -->",
        new_html
    )

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)

    print(f"Updated {INDEX_FILE} with {len(reviews)} review cards.")
    print(f"Timestamp: {timestamp}")


# ── MAIN ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    reviews = fetch_reviews()
    if not reviews:
        print("No reviews found — keeping existing cards unchanged.")
        sys.exit(0)
    update_index(reviews)
    print("\nDone.")
