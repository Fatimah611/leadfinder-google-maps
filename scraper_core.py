"""
Your Company Lead Finder — shared core logic
Used by both lead_finder.py (CLI) and app.py (web dashboard)
"""

import re
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

REQUEST_TIMEOUT = 8

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

SOCIAL_PATTERNS = {
    # (https?:)?// is optional now — catches "www.facebook.com/x" and
    # "//facebook.com/x" (protocol-relative), not just full "https://" links.
    # Also covers common alternate domains (m.facebook.com, fb.com, fb.watch,
    # business.facebook.com, instagr.am, wa.link).
    "facebook": re.compile(
        r"(?:https?:)?//(?:www\.|m\.|business\.)?(?:facebook\.com|fb\.com|fb\.watch)/[^\s\"'<>)\]]+",
        re.I),
    "instagram": re.compile(
        r"(?:https?:)?//(?:www\.)?(?:instagram\.com|instagr\.am)/[^\s\"'<>)\]]+",
        re.I),
    "linkedin": re.compile(
        r"(?:https?:)?//(?:www\.)?linkedin\.com/[^\s\"'<>)\]]+",
        re.I),
    "whatsapp": re.compile(
        r"(?:https?:)?//(?:wa\.me|api\.whatsapp\.com|wa\.link|chat\.whatsapp\.com)/[^\s\"'<>)\]]+",
        re.I),
}

EMAIL_BLOCKLIST_SUBSTR = ["example.com", "sentry.io", "wixpress.com", "godaddy.com", "yourdomain"]


def clean_url(url: str) -> str:
    url = url.rstrip("/\"'<>),.")
    if url.startswith("//"):
        url = "https:" + url
    return url


def safe_filename(text: str) -> str:
    """Turn 'Toronto' / 'Dental Clinic' into a filesystem-safe lowercase token."""
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return text.strip("_") or "leads"


def output_basename(city: str, category: str) -> str:
    """Each city+category combo gets its own file, so different searches never mix."""
    return f"leads_{safe_filename(city)}_{safe_filename(category)}"


def extract_from_html(html: str):
    emails = set(EMAIL_REGEX.findall(html))
    emails = {e for e in emails if not any(b in e.lower() for b in EMAIL_BLOCKLIST_SUBSTR)}

    socials = {}
    for platform, pattern in SOCIAL_PATTERNS.items():
        match = pattern.search(html)
        if match:
            socials[platform] = clean_url(match.group(0))

    return emails, socials


REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _get_rendered_html(browser, url: str):
    """
    Load a page with a real (headless) browser so JavaScript-injected content —
    e.g. social icons that Wix/Squarespace/Webflow/WordPress builders drop into
    the footer only after the page finishes loading — actually shows up in the
    HTML we scan. Falls back to a plain requests.get() if Playwright can't
    load it (some sites block headless browsers, some are just slow/broken).
    """
    try:
        pw_page = browser.new_page()
        try:
            pw_page.goto(url, timeout=REQUEST_TIMEOUT * 1000, wait_until="networkidle")
        except Exception:
            # networkidle can time out on sites with endless polling/analytics —
            # a partial load is still far better than nothing.
            pass

        # IMPORTANT: many modern site builders (Owner.com, Wix, Squarespace,
        # Webflow) lazy-load the FOOTER — which is exactly where the contact
        # email and social icons usually live — only once it scrolls into
        # view (IntersectionObserver). If we grab page content right after
        # goto() without ever scrolling, that footer never mounts into the
        # DOM and we silently miss real, present email/social links. So we
        # scroll down the page in a few steps (pausing briefly each time to
        # let lazy content mount) before reading the final HTML.
        try:
            prev_height = 0
            for _ in range(6):
                pw_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                pw_page.wait_for_timeout(400)
                curr_height = pw_page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    break
                prev_height = curr_height
            # small settle pause after the last scroll for any final lazy content
            pw_page.wait_for_timeout(300)
        except Exception:
            pass

        html = pw_page.content()
        pw_page.close()
        if html and len(html) > 200:
            return html
    except Exception:
        pass

    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        return resp.text
    except Exception:
        return ""


def enrich_website(url: str, browser=None):
    """
    Visit the homepage + a contact/about page if easy to find, return
    (email, socials dict). Uses a real headless browser when available so
    JS-rendered social links (very common — Wix, Squarespace, Webflow, WP
    page builders) are actually captured, not just what's in the raw HTML.
    """
    if not url:
        return "", {}

    found_emails = set()
    found_socials = {}

    def fetch(u):
        if browser is not None:
            return _get_rendered_html(browser, u)
        try:
            return requests.get(u, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT).text
        except Exception:
            return ""

    try:
        html = fetch(url)
        if not html:
            return "", {}

        emails, socials = extract_from_html(html)
        found_emails |= emails
        found_socials.update(socials)

        # Check a couple of likely extra pages (not just the first "contact"
        # link found) — social icons are sometimes only on /about or /contact,
        # not the homepage footer.
        soup = BeautifulSoup(html, "html.parser")
        candidate_urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            href_l = href.lower()
            if "contact" in href_l or "about" in href_l:
                full_url = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")
                if full_url not in candidate_urls:
                    candidate_urls.append(full_url)
            if len(candidate_urls) >= 2:
                break

        for extra_url in candidate_urls:
            if len(found_socials) >= 4 and found_emails:
                break  # already have everything we need, don't waste time
            extra_html = fetch(extra_url)
            if not extra_html:
                continue
            e2, s2 = extract_from_html(extra_html)
            found_emails |= e2
            for k, v in s2.items():
                found_socials.setdefault(k, v)

    except Exception:
        pass

    best_email = sorted(found_emails, key=len)[0] if found_emails else ""
    return best_email, found_socials


def find_qualifying_leads(query: str, city: str, category: str, target_count: int,
                           skip_names=None, log=print):
    """
    Discovers businesses on Google Maps AND enriches them (email + socials) in
    one pass, keeping only leads with at least one usable contact method
    (email, website, or a social link). Keeps scrolling/searching until
    `target_count` QUALIFYING leads are collected (not just target_count raw
    businesses found) — so the number you ask for is the number you get,
    minus whatever Google Maps simply runs out of results for.

    Returns a list of row dicts ready to be saved (business_name, email, city,
    website, category, facebook, instagram, linkedin, whatsapp).
    """
    seen_names = set(skip_names) if skip_names else set()
    qualifying_rows = []
    skipped_no_contact = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(
            f"https://www.google.com/maps/search/{query.replace(' ', '+')}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(4000)

        feed_selector = 'div[role="feed"]'
        try:
            page.wait_for_selector(feed_selector, timeout=10000)
        except Exception:
            log(f"! Could not load results feed for query: {query}")
            browser.close()
            return qualifying_rows

        last_seen_total = 0
        stagnant_rounds = 0
        # Give ourselves generous room to scroll since some businesses get filtered out
        max_stagnant_rounds = 8
        # Tracks the website URL recorded for the previously processed
        # business, so we can spot a stable-but-stale reading (see
        # panel-verification block below).
        last_panel_website = "__UNSET__"

        while len(qualifying_rows) < target_count and stagnant_rounds < max_stagnant_rounds:
            cards = page.query_selector_all(f'{feed_selector} a[href*="/maps/place/"]')

            for card in cards:
                if len(qualifying_rows) >= target_count:
                    break
                try:
                    name = card.get_attribute("aria-label")
                    if not name or name in seen_names:
                        continue
                    seen_names.add(name)

                    card.click()

                    # IMPORTANT: don't just sleep a fixed amount and hope the
                    # panel updated in time. Google Maps is a single-page app —
                    # panel refresh time varies (can take 800ms, can take 3s+).
                    # If we read the website before the NEW panel has loaded,
                    # we silently grab the PREVIOUS business's website and
                    # attach it to the CURRENT business's name — a one-row
                    # shift that gets worse the more it happens.
                    #
                    # (Earlier attempts checked page.title(), h1 text, and the
                    # page URL as PROXIES for "is the panel ready" — all three
                    # turned out to update at different, unreliable times
                    # relative to the sidebar's actual website link, which is
                    # the one thing we actually care about. So we stop
                    # guessing indirectly and instead poll THE EXACT FIELD
                    # we're about to record — the website href — until it
                    # reads the SAME value twice in a row. A stale value left
                    # over from the previous business would still be sitting
                    # there on the first read but get replaced before the
                    # second read; a genuinely-loaded value stays put.)
                    def _read_website_href():
                        try:
                            el = page.query_selector('a[data-item-id="authority"]')
                            return el.get_attribute("href") if el else None
                        except Exception:
                            return None

                    website = None
                    stable = False
                    prev_reading = "__UNSET__"
                    for attempt in range(20):  # up to ~10s, checked every 500ms
                        reading = _read_website_href()
                        if reading == prev_reading:
                            # Two consecutive identical reads. If this value
                            # is DIFFERENT from the previous business's
                            # website, we can trust it right away. If it
                            # happens to MATCH the previous business's
                            # website, give it a few more seconds first —
                            # that match is exactly the stale-data pattern
                            # we're guarding against — and only accept it as
                            # genuine once we've waited long enough that it's
                            # more likely to be a real (if coincidental)
                            # match than leftover stale content.
                            if reading != last_panel_website or attempt >= 6:
                                stable = True
                                website = reading
                                break
                        prev_reading = reading
                        page.wait_for_timeout(500)

                    if not stable:
                        # Never settled on a stable reading — safer to skip
                        # this business than risk attaching another
                        # business's website/socials to it.
                        log(f"  skipped: {name} (detail panel didn't load in time)")
                        continue

                    last_panel_website = website

                    email, socials = enrich_website(website, browser=browser)

                    has_any_contact = bool(email or website or socials.get("facebook")
                                            or socials.get("instagram") or socials.get("linkedin")
                                            or socials.get("whatsapp"))

                    if not has_any_contact:
                        skipped_no_contact += 1
                        log(f"  skipped: {name} (no email/website/social found)")
                        continue

                    qualifying_rows.append({
                        "business_name": name,
                        "email": email,
                        "city": city,
                        "website": website or "",
                        "category": category,
                        "facebook": socials.get("facebook", ""),
                        "instagram": socials.get("instagram", ""),
                        "linkedin": socials.get("linkedin", ""),
                        "whatsapp": socials.get("whatsapp", ""),
                    })
                    log(f"[{len(qualifying_rows)}/{target_count}] {name}")

                except Exception:
                    continue

            page.evaluate(f"document.querySelector('{feed_selector}').scrollBy(0, 1000)")
            page.wait_for_timeout(2000)

            total_processed = len(seen_names)
            if total_processed == last_seen_total:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            last_seen_total = total_processed

        browser.close()

    if len(qualifying_rows) < target_count:
        log(f"! Google Maps ran out of new results for '{query}' — "
            f"got {len(qualifying_rows)}/{target_count} qualifying leads "
            f"({skipped_no_contact} skipped for no contact info).")

    return qualifying_rows
