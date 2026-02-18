"""
LinkedIn Financial Planner Lead Scraper
========================================
סורק לינקדין לאיתור לידים של מתכננים פיננסיים פעילים

Flow:
  1. Login to LinkedIn (credentials or saved cookies)
  2. Search each keyword -> collect profile URLs
  3. For each profile: extract info + recent posts + engagement
  4. Score each lead (0-100)
  5. Filter by MIN thresholds
  6. Save to SQLite + CSV

Usage:
    python linkedin_scraper.py                  # run full scrape
    python linkedin_scraper.py --keywords "financial planner" "wealth manager"
    python linkedin_scraper.py --max 10 --no-headless
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import random
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

import linkedin_config as cfg

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("linkedin_scraper")


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------
@dataclass
class Lead:
    profile_url: str = ""
    name: str = ""
    title: str = ""
    location: str = ""
    connections: int = 0
    about_snippet: str = ""
    email: str = ""
    website: str = ""
    posts_analyzed: int = 0
    avg_comments: float = 0.0
    avg_likes: float = 0.0
    avg_shares: float = 0.0
    top_post_url: str = ""
    top_post_comments: int = 0
    keywords_found: str = ""      # comma-separated
    lead_score: float = 0.0
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rand_delay(lo: float | None = None, hi: float | None = None) -> None:
    lo = lo or cfg.REQUEST_DELAY_RANGE[0]
    hi = hi or cfg.REQUEST_DELAY_RANGE[1]
    time.sleep(random.uniform(lo, hi))


def _parse_count(text: str) -> int:
    """Convert '1,234', '1.2K', '3M+' etc. to int."""
    if not text:
        return 0
    text = text.strip().replace(",", "").replace("+", "").replace(" ", "")
    m = re.match(r"([\d.]+)([KMB]?)", text, re.I)
    if not m:
        return 0
    n = float(m.group(1))
    suffix = m.group(2).upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(n * multiplier)


def _score_by_bands(value: int, bands: list) -> float:
    for threshold, score in bands:
        if value >= threshold:
            return float(score)
    return 0.0


def compute_lead_score(lead: Lead) -> float:
    """Return a 0-100 composite score."""
    conn_score = _score_by_bands(lead.connections, cfg.CONNECTIONS_BANDS)
    comments_score = _score_by_bands(int(lead.avg_comments), cfg.AVG_COMMENTS_BANDS)

    # Post frequency (normalize: 10+ posts in window -> 100)
    freq_score = min(lead.posts_analyzed / max(cfg.MIN_POSTS_LAST_90_DAYS, 1), 1.0) * 100

    # Likes score (rough bands)
    likes_score = min(lead.avg_likes / 50.0, 1.0) * 100

    # Profile completeness
    completeness = sum([
        bool(lead.name),
        bool(lead.title),
        bool(lead.location),
        bool(lead.about_snippet),
        bool(lead.email or lead.website),
    ]) / 5.0 * 100

    weights = cfg.SCORE_WEIGHTS
    score = (
        weights["connections_score"]    * conn_score
        + weights["avg_comments_score"] * comments_score
        + weights["post_frequency_score"] * freq_score
        + weights["avg_likes_score"]    * likes_score
        + weights["profile_completeness"] * completeness
    )
    return round(score, 1)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class LeadStorage:
    def __init__(self):
        Path(cfg.OUTPUT_DIR).mkdir(exist_ok=True)
        self.conn = sqlite3.connect(cfg.OUTPUT_DB)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                profile_url       TEXT PRIMARY KEY,
                name              TEXT,
                title             TEXT,
                location          TEXT,
                connections       INTEGER,
                about_snippet     TEXT,
                email             TEXT,
                website           TEXT,
                posts_analyzed    INTEGER,
                avg_comments      REAL,
                avg_likes         REAL,
                avg_shares        REAL,
                top_post_url      TEXT,
                top_post_comments INTEGER,
                keywords_found    TEXT,
                lead_score        REAL,
                scraped_at        TEXT
            )
        """)
        self.conn.commit()

    def save(self, lead: Lead):
        d = asdict(lead)
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        self.conn.execute(
            f"INSERT OR REPLACE INTO leads ({cols}) VALUES ({placeholders})",
            list(d.values()),
        )
        self.conn.commit()

    def already_scraped(self, profile_url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM leads WHERE profile_url = ?", (profile_url,)
        ).fetchone()
        return row is not None

    def export_csv(self, min_score: float = 0.0) -> str:
        rows = self.conn.execute(
            "SELECT * FROM leads WHERE lead_score >= ? ORDER BY lead_score DESC",
            (min_score,),
        ).fetchall()
        col_names = [d[0] for d in self.conn.execute("PRAGMA table_info(leads)").fetchall()]
        with open(cfg.OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(col_names)
            writer.writerows(rows)
        return cfg.OUTPUT_CSV

    def summary(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        avg_score = self.conn.execute("SELECT AVG(lead_score) FROM leads").fetchone()[0] or 0
        top_leads = self.conn.execute(
            "SELECT name, title, connections, lead_score FROM leads ORDER BY lead_score DESC LIMIT 5"
        ).fetchall()
        return {
            "total_leads": total,
            "avg_score": round(avg_score, 1),
            "top_leads": top_leads,
        }

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# LinkedIn Browser Session
# ---------------------------------------------------------------------------

class LinkedInSession:
    """Manages a Playwright browser session authenticated to LinkedIn."""

    LOGIN_URL = "https://www.linkedin.com/login"
    FEED_URL  = "https://www.linkedin.com/feed/"
    SEARCH_PEOPLE_URL = (
        "https://www.linkedin.com/search/results/people/"
        "?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
    )

    def __init__(self, playwright: Playwright, headless: bool = True):
        self.playwright = playwright
        self.headless = headless
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self):
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(cfg.PAGE_LOAD_TIMEOUT)

    async def login(self) -> bool:
        """Login using saved cookies or credentials."""
        # Try saved cookies first
        if Path(cfg.COOKIES_FILE).exists():
            log.info("Loading saved cookies from %s", cfg.COOKIES_FILE)
            cookies = json.loads(Path(cfg.COOKIES_FILE).read_text())
            await self.context.add_cookies(cookies)
            await self.page.goto(self.FEED_URL, wait_until="domcontentloaded")
            _rand_delay(1, 2)
            if "feed" in self.page.url:
                log.info("Session restored from cookies.")
                return True
            log.warning("Cookies expired, falling back to credentials.")

        # Credential login
        email = cfg.LINKEDIN_EMAIL
        password = cfg.LINKEDIN_PASSWORD
        if not email or not password:
            raise RuntimeError(
                "Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD environment variables "
                "or provide linkedin_cookies.json."
            )

        log.info("Logging in to LinkedIn as %s ...", email)
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        await self.page.fill("#username", email)
        _rand_delay(0.5, 1.5)
        await self.page.fill("#password", password)
        _rand_delay(0.5, 1.0)
        await self.page.click('button[type="submit"]')
        await self.page.wait_for_load_state("domcontentloaded")
        _rand_delay(2, 4)

        if "checkpoint" in self.page.url or "challenge" in self.page.url:
            log.warning("LinkedIn security check triggered! Please complete it manually.")
            if not self.headless:
                input("Complete the security check in the browser, then press ENTER here...")
            else:
                raise RuntimeError("LinkedIn security checkpoint in headless mode. Run with --no-headless first to complete verification.")

        if "feed" not in self.page.url and "mynetwork" not in self.page.url:
            log.error("Login failed. Current URL: %s", self.page.url)
            return False

        # Save cookies for next run
        cookies = await self.context.cookies()
        Path(cfg.COOKIES_FILE).write_text(json.dumps(cookies, indent=2))
        log.info("Login successful. Cookies saved.")
        return True

    async def search_people(self, query: str, max_results: int) -> List[str]:
        """Search LinkedIn people and return list of profile URLs."""
        url = self.SEARCH_PEOPLE_URL.format(query=query.replace(" ", "%20"))
        log.info("Searching: %s (max %d results)", query, max_results)
        await self.page.goto(url, wait_until="domcontentloaded")
        _rand_delay(2, 3)

        profile_urls: List[str] = []
        page_num = 1

        while len(profile_urls) < max_results:
            # Extract profile links from search results
            links = await self.page.query_selector_all(
                "a.app-aware-link[href*='/in/']"
            )
            for link in links:
                href = await link.get_attribute("href")
                if href and "/in/" in href:
                    clean = href.split("?")[0].rstrip("/")
                    if clean not in profile_urls:
                        profile_urls.append(clean)
                if len(profile_urls) >= max_results:
                    break

            # Try next page
            next_btn = await self.page.query_selector('button[aria-label="Next"]')
            if not next_btn or len(profile_urls) >= max_results:
                break
            await next_btn.click()
            page_num += 1
            _rand_delay(2, 4)
            log.info("  page %d – %d profiles found so far", page_num, len(profile_urls))

        log.info("  -> %d profile URLs collected for '%s'", len(profile_urls), query)
        return profile_urls[:max_results]

    async def scrape_profile(self, profile_url: str) -> Lead:
        """Visit a profile page and extract lead data."""
        lead = Lead(profile_url=profile_url)

        # --- Main profile page ---
        try:
            await self.page.goto(profile_url, wait_until="domcontentloaded")
            _rand_delay(1.5, 3)
        except Exception as exc:
            log.warning("Could not load profile %s: %s", profile_url, exc)
            return lead

        # Scroll a bit to trigger lazy-load
        await self.page.evaluate("window.scrollBy(0, 600)")
        await asyncio.sleep(cfg.SCROLL_PAUSE)

        # Name
        name_el = await self.page.query_selector("h1.text-heading-xlarge")
        if name_el:
            lead.name = (await name_el.inner_text()).strip()

        # Title / Headline
        title_el = await self.page.query_selector("div.text-body-medium.break-words")
        if title_el:
            lead.title = (await title_el.inner_text()).strip()

        # Location
        loc_el = await self.page.query_selector("span.text-body-small.inline.t-black--light")
        if loc_el:
            lead.location = (await loc_el.inner_text()).strip()

        # Connections / Followers
        conn_el = await self.page.query_selector(
            "span.t-bold ~ span.t-normal"
        )
        # Try multiple selectors for connections count
        for selector in [
            "span[data-test-id='connection-badge']",
            "span.t-bold",
            "li.text-body-small span",
        ]:
            els = await self.page.query_selector_all(selector)
            for el in els:
                txt = (await el.inner_text()).strip()
                if any(w in txt.lower() for w in ["connection", "follower", "connections", "followers"]):
                    numbers = re.findall(r"[\d,KkMm+]+", txt)
                    if numbers:
                        lead.connections = _parse_count(numbers[0])
                        break
            if lead.connections:
                break

        # Also check the profile "followers" badge
        if not lead.connections:
            badges = await self.page.query_selector_all(
                "div.pvs-header__container span"
            )
            for badge in badges:
                txt = (await badge.inner_text()).strip()
                if "follower" in txt.lower():
                    n = re.findall(r"[\d,KkMm.+]+", txt)
                    if n:
                        lead.connections = _parse_count(n[0])
                        break

        # About / Summary
        about_el = await self.page.query_selector(
            "div[data-generated-suggestion-target] span[aria-hidden='true']"
        )
        if not about_el:
            about_el = await self.page.query_selector("section.artdeco-card div.display-flex span")
        if about_el:
            txt = (await about_el.inner_text()).strip()
            lead.about_snippet = txt[:300]

        # Contact info (opens modal)
        try:
            contact_btn = await self.page.query_selector("a[href*='contact-info']")
            if contact_btn:
                await contact_btn.click()
                await asyncio.sleep(1.5)
                contact_html = await self.page.inner_text("div.artdeco-modal__content")
                # Email
                email_match = re.search(r"[\w.+-]+@[\w-]+\.\w+", contact_html)
                if email_match:
                    lead.email = email_match.group()
                # Website
                web_match = re.search(r"https?://[^\s\"'<>]+", contact_html)
                if web_match and "linkedin.com" not in web_match.group():
                    lead.website = web_match.group()[:100]
                # Close modal
                close_btn = await self.page.query_selector("button[data-test-modal-close-btn]")
                if close_btn:
                    await close_btn.click()
                    await asyncio.sleep(0.5)
        except Exception:
            pass  # contact info not critical

        # Product relevance keywords
        full_text = f"{lead.title} {lead.about_snippet}".lower()
        found_kw = [kw for kw in cfg.PRODUCT_RELEVANCE_KEYWORDS if kw.lower() in full_text]
        lead.keywords_found = ", ".join(found_kw)

        # --- Analyse recent posts ---
        await self._analyze_posts(lead)

        # --- Compute final score ---
        lead.lead_score = compute_lead_score(lead)
        log.info(
            "  Scraped: %-30s | conn=%5d | avg_comments=%.1f | score=%.1f",
            lead.name[:30], lead.connections, lead.avg_comments, lead.lead_score,
        )
        return lead

    async def _analyze_posts(self, lead: Lead):
        """Visit the profile activity page and extract post engagement stats."""
        activity_url = lead.profile_url.rstrip("/") + "/recent-activity/shares/"
        try:
            await self.page.goto(activity_url, wait_until="domcontentloaded")
            _rand_delay(1.5, 3)
        except Exception:
            return

        # Scroll to load more posts
        for _ in range(3):
            await self.page.evaluate("window.scrollBy(0, 1000)")
            await asyncio.sleep(cfg.SCROLL_PAUSE)

        # Find post containers
        post_els = await self.page.query_selector_all(
            "div.feed-shared-update-v2, div.occludable-update"
        )

        comments_list: List[int] = []
        likes_list: List[int] = []
        shares_list: List[int] = []
        top_comments = 0
        top_post_url = ""

        for post_el in post_els[: cfg.MAX_POSTS_TO_ANALYZE]:
            try:
                # Engagement counts – they live in the social-counts bar
                social_text = await post_el.inner_text()

                # Comments
                c_match = re.search(r"([\d,KkMm]+)\s+comment", social_text, re.I)
                c = _parse_count(c_match.group(1)) if c_match else 0
                comments_list.append(c)

                # Reactions / Likes
                r_match = re.search(r"([\d,KkMm]+)\s+(?:reaction|like)", social_text, re.I)
                r = _parse_count(r_match.group(1)) if r_match else 0
                likes_list.append(r)

                # Shares / Reposts
                s_match = re.search(r"([\d,KkMm]+)\s+(?:repost|share)", social_text, re.I)
                s = _parse_count(s_match.group(1)) if s_match else 0
                shares_list.append(s)

                # Track top post
                if c > top_comments:
                    top_comments = c
                    # Try to get permalink
                    link_el = await post_el.query_selector(
                        "a[href*='/posts/'], a[href*='/feed/update/']"
                    )
                    if link_el:
                        top_post_url = (await link_el.get_attribute("href") or "").split("?")[0]
            except Exception:
                continue

        if comments_list:
            lead.posts_analyzed = len(comments_list)
            lead.avg_comments = round(sum(comments_list) / len(comments_list), 1)
            lead.avg_likes    = round(sum(likes_list)    / len(likes_list),    1) if likes_list else 0
            lead.avg_shares   = round(sum(shares_list)   / len(shares_list),   1) if shares_list else 0
            lead.top_post_url      = top_post_url
            lead.top_post_comments = top_comments

    async def close(self):
        if self.browser:
            await self.browser.close()


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

async def run_scraper(
    keywords: List[str] | None = None,
    max_per_keyword: int | None = None,
    headless: bool = True,
    min_score: float = 20.0,
) -> LeadStorage:
    keywords      = keywords      or cfg.SEARCH_KEYWORDS
    max_per_kw    = max_per_keyword or cfg.MAX_RESULTS_PER_KEYWORD

    storage = LeadStorage()
    new_leads = 0
    skipped   = 0

    async with async_playwright() as pw:
        session = LinkedInSession(pw, headless=headless)
        await session.start()

        logged_in = await session.login()
        if not logged_in:
            log.error("Authentication failed. Aborting.")
            await session.close()
            return storage

        all_profile_urls: List[str] = []

        # Phase 1: collect profile URLs from search results
        for kw in keywords:
            urls = await session.search_people(kw, max_per_kw)
            for url in urls:
                if url not in all_profile_urls:
                    all_profile_urls.append(url)
            _rand_delay(3, 6)

        log.info("Total unique profiles to scrape: %d", len(all_profile_urls))

        # Phase 2: scrape each profile
        for i, url in enumerate(all_profile_urls, 1):
            log.info("[%d/%d] %s", i, len(all_profile_urls), url)

            if storage.already_scraped(url):
                log.info("  -> already in DB, skipping.")
                skipped += 1
                continue

            lead = await session.scrape_profile(url)

            # Apply minimum filters
            qualifies = (
                lead.connections >= cfg.MIN_CONNECTIONS
                and lead.avg_comments >= cfg.MIN_AVG_COMMENTS
                and lead.posts_analyzed >= cfg.MIN_POSTS_LAST_90_DAYS
            )
            if qualifies or lead.lead_score >= min_score:
                storage.save(lead)
                new_leads += 1
                log.info("  -> SAVED  score=%.1f", lead.lead_score)
            else:
                log.info(
                    "  -> FILTERED OUT  (conn=%d, avg_comments=%.1f, posts=%d)",
                    lead.connections, lead.avg_comments, lead.posts_analyzed,
                )

            _rand_delay()

        await session.close()

    # Export CSV
    csv_path = storage.export_csv(min_score=0)
    summary  = storage.summary()

    log.info("=" * 60)
    log.info("DONE. New leads saved: %d  |  Skipped (already in DB): %d", new_leads, skipped)
    log.info("Total leads in DB: %d  |  Avg score: %.1f", summary["total_leads"], summary["avg_score"])
    log.info("Top leads:")
    for row in summary["top_leads"]:
        log.info("  %-25s | %-35s | conn=%-6s | score=%.1f", *row)
    log.info("CSV exported to: %s", csv_path)
    log.info("DB path: %s", cfg.OUTPUT_DB)

    return storage


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Financial Planner Lead Scraper"
    )
    parser.add_argument(
        "--keywords", nargs="+",
        help="Search keywords (overrides config). Example: --keywords 'financial planner' CFP"
    )
    parser.add_argument(
        "--max", type=int, default=None,
        help=f"Max results per keyword (default: {cfg.MAX_RESULTS_PER_KEYWORD})"
    )
    parser.add_argument(
        "--no-headless", action="store_true",
        help="Show browser window (useful for initial login / CAPTCHA)"
    )
    parser.add_argument(
        "--min-score", type=float, default=20.0,
        help="Minimum lead score to save (default: 20)"
    )
    args = parser.parse_args()

    asyncio.run(
        run_scraper(
            keywords=args.keywords,
            max_per_keyword=args.max,
            headless=not args.no_headless,
            min_score=args.min_score,
        )
    )


if __name__ == "__main__":
    main()
