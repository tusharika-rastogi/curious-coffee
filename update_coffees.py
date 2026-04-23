#!/usr/bin/env python3
"""
update_coffees.py
Scrapes curious-coffee.com for all coffee products and rebuilds
the coffee cards section in index.html.

Run manually:  python3 update_coffees.py
Run via CI:    GitHub Actions calls this daily at 6pm EST
"""

import re
import sys
import time
import json
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────
SHOP_URL      = "https://www.curious-coffee.com"
INDEX_FILE    = "index.html"
SHOW_INITIALLY = 8   # cards visible before "See All"

# Category mapping by URL slug (kept up to date manually or extended below)
CATEGORY_MAP = {
    # STANDARD
    "danche-red-honey":                     "standard",
    "andrés-martinez-caturra-floral":       "standard",
    "andrés-caturra-floral":                "standard",
    "fazenda-guariroba-pink-bourbon":       "standard",
    "finca-el-socorro-low-caffeine":        "standard",
    "fazenda-matão":                        "standard",
    "fazenda-mat":                          "standard",
    "fazenda-são-domingos":                 "standard",
    "fazenda-sao-domingos":                 "standard",
    "seasonal-espresso-blend":              "standard",
    "peru-organic-fairtrade-washed-process-1": "standard",
    # PREMIUM  (everything else is premium by default)
}

# Farm images that contain faces/people -> use object-position:top
# and specific ones that need top-left
FACE_TOP_HASHES = {
    "d6df75ab",  # Jairo Arcila smiling
    "c8644956",  # Jairo Arcila farm with person
    "1a2930e5",  # shared producer portrait (Dinestia / Bella Alejandria)
}
FACE_TOP_LEFT_HASHES = {
    "05057603",  # Andrés Martinez pointing at cherries
}


# ── HTML PARSER ────────────────────────────────────────────────────────────
class ShopParser(HTMLParser):
    """Minimal parser to extract product links and basic info from the shop page."""

    def __init__(self):
        super().__init__()
        self.products = []      # list of {url, name, price, oos, img}
        self._in_product = False
        self._current = {}
        self._capture_text = False
        self._text_buf = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href", "")
        # Product links contain /product-page/
        if tag == "a" and "/product-page/" in href:
            self._current = {"url": href, "name": "", "price": "", "oos": False, "img": ""}
            self._in_product = True
        if self._in_product and tag == "img" and not self._current.get("img"):
            src = attrs.get("src", "")
            if "wixstatic" in src and "~mv2" in src:
                self._current["img"] = src

    def handle_endtag(self, tag):
        if self._in_product and tag == "a" and self._current.get("url"):
            if self._current.get("name"):
                self.products.append(dict(self._current))
            self._current = {}
            self._in_product = False

    def handle_data(self, data):
        if not self._in_product:
            return
        text = data.strip()
        if not text:
            return
        if not self._current.get("name") and len(text) > 3 and text[0].isupper():
            self._current["name"] = text
        if "$" in text and not self._current.get("price"):
            self._current["price"] = text.strip()
        if "Out of stock" in text or "Out of Stock" in text:
            self._current["oos"] = True


class ProductPageParser(HTMLParser):
    """Extracts description text and secondary (farm) image from a product page."""

    def __init__(self):
        super().__init__()
        self.description = ""
        self.farm_img    = ""
        self.all_imgs    = []
        self._in_pre     = False
        self._pre_buf    = ""
        self._found_pre  = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            src = attrs.get("src", "")
            if "wixstatic" in src and "~mv2" in src:
                self.all_imgs.append(src)

    def handle_data(self, data):
        pass  # description comes from raw pre/code block in Wix HTML

    def get_farm_img(self):
        """Return second image (farm photo) or first if only one."""
        # Filter to non-blurred images only
        clean = [i for i in self.all_imgs if "blur" not in i and "data:image" not in i]
        if len(clean) >= 2:
            return clean[1]
        elif clean:
            return clean[0]
        return ""


# ── FETCH HELPERS ──────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

def _safe_url(url):
    """Percent-encode non-ASCII characters in a URL so urllib can handle them."""
    return urllib.parse.quote(url, safe=":/?=#&%+")

def fetch(url, retries=3, delay=2):
    url = _safe_url(url)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Attempt {attempt+1} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
    return ""


def _og_meta(html, prop):
    """Return the content= of an Open Graph <meta> tag (server-rendered by Wix)."""
    for pat in [
        rf'<meta[^>]+property=["\']og:{prop}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:{prop}["\']',
    ]:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def extract_description(html):
    """Pull structured product description from pre/code block, or fall back to og:description."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", html, re.DOTALL)
    if not m:
        m = re.search(r"<code[^>]*>(.*?)</code>", html, re.DOTALL)
    if m:
        raw = m.group(1)
        # Wix stores fields in <span> elements; replace closing block tags with
        # newlines so "Field: X</span><span>Field: Y" doesn't collapse to "Field: XField: Y"
        raw = re.sub(r"</(?:span|p|div|li|td)[^>]*>", "\n", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", raw)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&#39;", "'").replace("&quot;", '"').replace("&nbsp;", " ").replace("\xa0", " ")
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if lines:
            return "\n".join(lines)
    return _og_meta(html, "description")


# Lookahead that stops field-value capture at the next known field name + colon.
# Requiring the colon prevents "Farm Valley" in an origin value from triggering a stop.
_FIELD_STOP = r"(?=(?:Farm|Origin|Variety|Varietal|Process|Notes?|Altitude|Elevation|Producers?|Region)\s*:|Rest[^:\n]*:|Brewing[^:\n]*:|\Z)"

_FIELD_LINE_RE = re.compile(
    r"^(?:Farm|Origin|Variety|Varietal|Process|Notes?|Altitude|Elevation|Producers?|Region|Farmer|Rest[^:]*|Brewing[^:]*)\s*:",
    re.IGNORECASE,
)

def extract_narrative(description):
    """Return only the prose lines from a description, stripping field-label lines."""
    lines = description.splitlines()
    prose = [l for l in lines if not _FIELD_LINE_RE.match(l.strip())]
    # Collapse runs of blank lines and strip leading/trailing whitespace
    text = "\n".join(prose).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def _wix_imgs(html):
    """Deduplicated Wix CDN image URLs from script-tag JSON (where Wix embeds all product images)."""
    seen = []
    for script_m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        content = script_m.group(1)
        if "wixstatic" not in content:
            continue
        for url in re.findall(
            r"https://static\.wixstatic\.com/media/[^\"'\\]+?~mv2\.[a-z]+",
            content,
        ):
            if "blur" not in url and url not in seen:
                seen.append(url)
    return seen


def extract_bag_img(html):
    """Product/bag image: og:image is server-rendered and most reliable."""
    url = _og_meta(html, "image")
    if url and "wixstatic" in url:
        # Strip size params so we get the original, then re-parameterise for display
        base = url.split("/v1/")[0]
        return base + "/v1/fill/w_600,h_600,al_c,q_85/file.jpg"
    imgs = _wix_imgs(html)
    return imgs[0] if imgs else ""


def _wix_crop(base_url, w, h, align="t"):
    """Return a Wix fill URL with server-side crop; strips any existing /v1/ params first."""
    base = base_url.split("/v1/")[0]
    return f"{base}/v1/fill/w_{w},h_{h},al_{align},q_85/file.jpg"


def extract_farm_img(html):
    """Farm/secondary image: second script-tag URL; fallback to og:image.
    Requests a top-aligned crop so faces stay in frame."""
    imgs = _wix_imgs(html)
    if len(imgs) >= 2:
        return _wix_crop(imgs[1], 600, 400)
    url = _og_meta(html, "image")
    if url and "wixstatic" in url:
        return _wix_crop(url, 600, 400)
    return imgs[0] if imgs else ""


# ── CATEGORY & POSITION HELPERS ────────────────────────────────────────────
def get_category(url):
    slug = url.split("/product-page/")[-1].lower()
    for key, cat in CATEGORY_MAP.items():
        if key in slug:
            return cat
    return "premium"  # default


def get_object_position(farm_img_url):
    for h in FACE_TOP_LEFT_HASHES:
        if h in farm_img_url:
            return "top left"
    for h in FACE_TOP_HASHES:
        if h in farm_img_url:
            return "top"
    # Check dimensions from URL
    w = re.search(r"w_(\d+)", farm_img_url)
    h = re.search(r"h_(\d+)", farm_img_url)
    if w and h and int(w.group(1)) > int(h.group(1)):
        return "center"   # clearly landscape — scenery, no face at top
    return "top"          # portrait or unknown: keep faces in frame


# ── CARD BUILDER ───────────────────────────────────────────────────────────
PILL_COLORS = ["g", "t", "g", "t", "g"]  # alternate green/teal

def build_tasting_pills(notes_text):
    """Extract tasting notes and build pill HTML."""
    m = re.search(r"[Nn]otes?[:\s]+(.+?)" + _FIELD_STOP, notes_text, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1).strip().rstrip(".")
    # Split on comma or semicolon; discard items that look like sentences (long or contain periods)
    items = [
        n.strip() for n in re.split(r"[,;]", raw)
        if n.strip() and len(n.strip()) <= 35 and "." not in n
    ][:4]
    if not items:
        return ""
    pills = []
    for i, item in enumerate(items):
        color = PILL_COLORS[i % len(PILL_COLORS)]
        pills.append(f'<span class="pill {color}">{item.capitalize()}</span>')
    return "".join(pills)


_FIELD_ORDER = ["Farm", "Origin", "Variety", "Process", "Notes", "Brewing", "Rest from roast"]

def build_fields_html(fields):
    rows = []
    for key in _FIELD_ORDER:
        val = (fields.get(key) or "").strip()
        if val:
            rows.append(
                f'<div class="field-row">'
                f'<span class="field-key">{key}</span>'
                f'<span class="field-val">{val}</span>'
                f'</div>'
            )
    return '<div class="back-fields">' + "".join(rows) + "</div>" if rows else ""


def build_card(cid, name, variety, origin_line, price, oos,
               bag_img, farm_img, back_lbl, fields, raw_description, link, category, hidden):

    notes_html = build_tasting_pills(raw_description)
    if not notes_html:
        notes_html = '<span class="pill g">Specialty Coffee</span>'

    obj_pos = get_object_position(farm_img)
    hidden_attr = ' style="display:none"' if hidden else ""
    oos_badge = '<span class="oos-badge">Out of Stock</span>' if oos else ""

    cat_label = ""
    if category in ("standard", "premium"):
        label_text = "Standard" if category == "standard" else "Premium"
        cat_label = f'<span class="cat-label cat-{category}">{label_text}</span>\n              '

    if oos:
        buy_btn  = '<span class="card-btn oos-btn" aria-disabled="true">Out of Stock</span>'
        back_btn = '<span class="back-btn oos-back">Out of Stock</span>'
        price_cls = "oos-price"
    else:
        buy_btn  = f'<a href="{link}" target="_blank" rel="noopener" class="card-btn">Buy This Bag</a>'
        back_btn = f'<a href="{link}" target="_blank" rel="noopener" class="back-btn">Buy Now {price}</a>'
        price_cls = ""

    return f"""
      <div class="flip-wrap reveal" data-card-id="{cid}"{hidden_attr} role="article">
        <div class="flip-inner">
          <div class="flip-front">
            {oos_badge}
            <div class="card-img-wrap">
              <img src="{bag_img}" alt="{name} bag" loading="lazy"/>
            </div>
            <div class="card-body">
              <span class="card-origin">{origin_line}</span>
              <h3 class="card-producer">{name}</h3>
              <p class="card-variety">{variety}</p>
              {cat_label}<div class="card-notes">{notes_html}</div>
              <div class="card-ft">
                <span class="card-price {price_cls}">{price}</span>
                {buy_btn}
              </div>
            </div>
          </div>
          <div class="flip-back">
            <img class="back-img" style="object-position:{obj_pos}" src="{farm_img}" alt="{name} farm" loading="lazy"/>
            <div class="back-body">
              <span class="back-lbl">{back_lbl}</span>
              <h3 class="back-title">{name}</h3>
              {build_fields_html(fields)}
              {back_btn}
            </div>
          </div>
        </div>
      </div>"""


# ── SCRAPE SHOP ─────────────────────────────────────────────────────────────
def scrape_shop():
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M}] Scraping {SHOP_URL} ...")

    html = fetch(SHOP_URL)
    if not html:
        print("ERROR: Could not fetch shop page.")
        sys.exit(1)

    # Find all product-page links
    links = list(dict.fromkeys(
        re.findall(r'href="(https://www\.curious-coffee\.com/product-page/[^"]+)"', html)
    ))
    print(f"Found {len(links)} product links")

    # Filter: skip non-coffee items
    SKIP_SLUGS = ["curious-coffee-club", "monthly-coffee-subscription",
                  "gift-card", "lotus-coffee-water-drops", "brewing"]

    coffees = []
    for url in links:
        slug = url.split("/product-page/")[-1].lower()
        if any(s in slug for s in SKIP_SLUGS):
            print(f"  Skipping: {slug}")
            continue

        print(f"  Fetching: {slug[:50]}")
        page_html = fetch(url)
        time.sleep(0.5)  # be polite

        if not page_html:
            continue

        # Extract data
        bag_img     = extract_bag_img(page_html)
        farm_img    = extract_farm_img(page_html)
        description = extract_description(page_html)
        oos         = bool(re.search(r"Out of [Ss]tock", page_html))
        category    = get_category(url)

        # Extract price
        price_m = re.search(r'\$[\d,]+\.?\d*(?:/\d+oz)?', page_html)
        price = price_m.group(0) if price_m else "Price on site"

        # Product name from <h1>
        name_m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.DOTALL)
        name = re.sub(r"<[^>]+>", "", name_m.group(1)).strip() if name_m else slug.replace("-", " ").title()

        def _field(m, maxlen=80):
            """Return cleaned match group(1), or '' if suspiciously long (bad parse)."""
            if not m:
                return ""
            val = m.group(1).strip().rstrip(".").strip()
            return val if len(val) <= maxlen else ""

        # Origin line — colon format first, then tabular "Location\nvalue" fallback
        origin_m = (
            re.search(r"(?:^|\n)[Oo]rigin\s*:\s*(.+?)" + _FIELD_STOP, description, re.DOTALL | re.MULTILINE)
            or re.search(r"(?:^|\n)[Rr]egion\s*:\s*(.+?)" + _FIELD_STOP, description, re.DOTALL | re.MULTILINE)
            or re.search(r"(?:^|\n)Location\s*\n([^\n]+)", description, re.MULTILINE)
        )
        origin_line = _field(origin_m) or "Specialty Coffee"

        # Variety — "Cultivar\nvalue" tabular fallback for Jairo Arcila style
        var_m = (
            re.search(r"(?:^|\n)[Vv]ariet(?:y|ies)?\s*:\s*(.+?)" + _FIELD_STOP, description, re.DOTALL | re.MULTILINE)
            or re.search(r"(?:^|\n)Cultivar\s*\n([^\n]+)", description, re.MULTILINE)
        )
        variety = _field(var_m)

        # Back label (altitude / elevation) — tabular "Altitude\nvalue" fallback
        alt_m = (
            re.search(r"(?:^|\n)(?:[Aa]ltitude|[Ee]levation)\s*:\s*(.+?)" + _FIELD_STOP, description, re.DOTALL | re.MULTILINE)
            or re.search(r"(?:^|\n)Altitude\s*\n([^\n]+)", description, re.MULTILINE)
        )
        alt_txt = _field(alt_m, maxlen=30)
        back_lbl = f"{origin_line}" + (f" &middot; {alt_txt}" if alt_txt else "")

        # Additional structured fields for back card.
        # All patterns require colon + line-start to avoid matching words inside narrative prose.
        MF = re.DOTALL | re.MULTILINE

        farm_m    = re.search(r"(?:^|\n)[Ff]arm\s*:\s*(.+?)" + _FIELD_STOP, description, MF)
        farm_name = _field(farm_m, maxlen=100)

        # Tabular fallback: "Process\nhoney process..." (Jairo Arcila style, no colon)
        process_m = (re.search(r"(?:^|\n)[Pp]rocess\s*:\s*(.+?)" + _FIELD_STOP, description, MF)
                     or re.search(r"(?:^|\n)Process\s*\n([^\n]+)", description, re.MULTILINE))
        process   = _field(process_m, maxlen=80)

        notes_m   = re.search(r"(?:^|\n)[Nn]otes?\s*:\s*(.+?)" + _FIELD_STOP, description, MF)
        notes_txt = _field(notes_m, maxlen=200)

        brewing_m = re.search(r"(?:^|\n)[Bb]rewing[^:]*:\s*(.+?)" + _FIELD_STOP, description, MF)
        brewing   = _field(brewing_m, maxlen=300)

        rest_m    = re.search(r"(?:^|\n)[Rr]est[^:]*:\s*([^\n]+)", description, re.MULTILINE)
        rest      = _field(rest_m, maxlen=150)

        coffees.append({
            "url":         url,
            "name":        name,
            "variety":     variety,
            "origin":      origin_line,
            "price":       price,
            "oos":         oos,
            "bag_img":     bag_img,
            "farm_img":    farm_img or bag_img,
            "back_lbl":    back_lbl,
            "raw_description": description,
            "fields": {
                "Farm":            farm_name,
                "Origin":          origin_line if origin_line != "Specialty Coffee" else "",
                "Variety":         variety,
                "Process":         process,
                "Notes":           notes_txt,
                "Brewing":         brewing,
                "Rest from roast": rest,
            },
            "category":    category,
        })

    # Sort: in-stock first, then out-of-stock
    coffees.sort(key=lambda c: (1 if c["oos"] else 0, c["name"].lower()))

    print(f"\nTotal coffees scraped: {len(coffees)}")
    print(f"  In stock:     {sum(1 for c in coffees if not c['oos'])}")
    print(f"  Out of stock: {sum(1 for c in coffees if c['oos'])}")
    return coffees


# ── BUILD HTML CARDS ─────────────────────────────────────────────────────────
def build_cards_html(coffees):
    cards_html = []
    for i, c in enumerate(coffees):
        cid    = i + 1
        hidden = cid > SHOW_INITIALLY
        card   = build_card(
            cid             = cid,
            name            = c["name"],
            variety         = c["variety"],
            origin_line     = c["origin"],
            price           = c["price"],
            oos             = c["oos"],
            bag_img         = c["bag_img"],
            farm_img        = c["farm_img"],
            back_lbl        = c["back_lbl"],
            fields          = c["fields"],
            raw_description = c["raw_description"],
            link            = c["url"],
            category        = c["category"],
            hidden          = hidden,
        )
        cards_html.append(card)
    return "\n".join(cards_html)


# ── INJECT INTO INDEX.HTML ────────────────────────────────────────────────
CARDS_START = "<!-- COFFEE_CARDS_START -->"
CARDS_END   = "<!-- COFFEE_CARDS_END -->"
def extract_existing_images(html):
    """Return {product_name_lower: (bag_img, farm_img)} from the current cards section."""
    existing = {}
    cards_section_m = re.search(
        r"<!-- COFFEE_CARDS_START -->(.*?)<!-- COFFEE_CARDS_END -->", html, re.DOTALL
    )
    if not cards_section_m:
        return existing
    section = cards_section_m.group(1)
    # Each card block
    for card in re.finditer(r'<div class="flip-wrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', section, re.DOTALL):
        block = card.group(1)
        name_m = re.search(r'class="card-producer"[^>]*>([^<]+)', block)
        bag_m  = re.search(r'card-img-wrap.*?<img[^>]+src="([^"]+)"', block, re.DOTALL)
        farm_m = re.search(r'class="back-img"[^>]+src="([^"]+)"', block)
        if name_m:
            name = name_m.group(1).strip().lower()
            bag  = bag_m.group(1)  if bag_m  and bag_m.group(1)  else ""
            farm = farm_m.group(1) if farm_m and farm_m.group(1) else ""
            if bag or farm:
                existing[name] = (bag, farm)
    return existing


def update_index(coffees):
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print(f"ERROR: {INDEX_FILE} not found. Run from the repo root.")
        sys.exit(1)

    # Check markers exist
    if CARDS_START not in html or CARDS_END not in html:
        print(f"ERROR: Markers {CARDS_START!r} and {CARDS_END!r} not found in {INDEX_FILE}.")
        print("Add these HTML comments around the coffee cards grid in index.html:")
        print(f"  {CARDS_START}")
        print("  ... all the flip-wrap divs ...")
        print(f"  {CARDS_END}")
        sys.exit(1)

    # Preserve existing image URLs so a failed scrape never wipes them
    existing_imgs = extract_existing_images(html)
    for c in coffees:
        if not c["bag_img"] or not c["farm_img"]:
            fallback = existing_imgs.get(c["name"].lower(), ("", ""))
            if not c["bag_img"]:
                c["bag_img"] = fallback[0]
                if fallback[0]:
                    print(f"  Using existing bag image for: {c['name']}")
            if not c["farm_img"]:
                c["farm_img"] = fallback[1] or fallback[0]
                if fallback[1] or fallback[0]:
                    print(f"  Using existing farm image for: {c['name']}")

    cards_html = build_cards_html(coffees)

    # Replace between markers
    start_idx = html.index(CARDS_START) + len(CARDS_START)
    end_idx   = html.index(CARDS_END)
    new_html  = html[:start_idx] + "\n" + cards_html + "\n    " + html[end_idx:]

    # Update JS SHOW constant
    new_html = re.sub(
        r"const SHOW=\d+;",
        f"const SHOW={SHOW_INITIALLY};",
        new_html
    )

    # Add timestamp comment
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    new_html = re.sub(
        r"<!-- Last updated: .* -->",
        f"<!-- Last updated: {timestamp} -->",
        new_html
    )
    if "<!-- Last updated:" not in new_html:
        new_html = new_html.replace(
            "<!-- COFFEE_CARDS_START -->",
            f"<!-- Last updated: {timestamp} -->\n    <!-- COFFEE_CARDS_START -->"
        )

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)

    hidden_count = max(0, len(coffees) - SHOW_INITIALLY)
    print(f"\nUpdated {INDEX_FILE} with {len(coffees)} coffee cards ({hidden_count} hidden).")
    print(f"Timestamp: {timestamp}")


# ── MAIN ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    coffees = scrape_shop()
    if not coffees:
        print("No coffees found. Aborting to avoid wiping cards.")
        sys.exit(1)
    update_index(coffees)
    print("\nDone.")
