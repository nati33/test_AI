"""
LinkedIn Financial Planner Lead Scraper - Configuration
========================================================
הגדרות כלי סריקת לינקדין למציאת לידים של מתכננים פיננסיים

IMPORTANT: Usage must comply with LinkedIn's Terms of Service.
This tool is intended for authorized business development purposes only.
"""

import os

# ---------------------------------------------------------------------------
# LinkedIn Credentials (set via environment variables or .env file)
# ---------------------------------------------------------------------------
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

# Path to saved session cookies (avoids re-login on each run)
COOKIES_FILE = "linkedin_cookies.json"

# ---------------------------------------------------------------------------
# Search Keywords
# ---------------------------------------------------------------------------
# English keywords
SEARCH_KEYWORDS_EN = [
    "financial planner",
    "certified financial planner CFP",
    "financial advisor",
    "wealth manager",
    "investment advisor",
    "retirement planner",
    "personal finance coach",
]

# Hebrew keywords
SEARCH_KEYWORDS_HE = [
    "מתכנן פיננסי",
    "יועץ פיננסי",
    "מתכנן פרישה",
    "מנהל עושר",
    "יועץ השקעות",
]

# Combined (used by default)
SEARCH_KEYWORDS = SEARCH_KEYWORDS_EN + SEARCH_KEYWORDS_HE

# ---------------------------------------------------------------------------
# Lead Qualification Filters
# ---------------------------------------------------------------------------
# Minimum follower/connection count to be considered a lead
MIN_CONNECTIONS = 300

# Minimum posts in the last 90 days to be considered "active"
MIN_POSTS_LAST_90_DAYS = 3

# Minimum average comments per post (shows engaged audience)
MIN_AVG_COMMENTS = 2

# ---------------------------------------------------------------------------
# Lead Scoring Weights  (must sum to 1.0)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "connections_score": 0.15,      # Audience size
    "post_frequency_score": 0.20,   # How often they post
    "avg_comments_score": 0.30,     # Comments = engaged audience (highest weight)
    "avg_likes_score": 0.15,        # Likes
    "profile_completeness": 0.20,   # Complete profile = serious professional
}

# Thresholds for scoring bands
CONNECTIONS_BANDS = [
    (10_000, 100),
    (5_000,   80),
    (2_000,   60),
    (1_000,   40),
    (500,     20),
    (0,       10),
]

AVG_COMMENTS_BANDS = [
    (50,  100),
    (20,   80),
    (10,   60),
    (5,    40),
    (2,    20),
    (0,    5),
]

# ---------------------------------------------------------------------------
# Product Offer Tags - keywords that increase lead relevance
# ---------------------------------------------------------------------------
PRODUCT_RELEVANCE_KEYWORDS = [
    "financial planning software",
    "fintech",
    "planning tool",
    "client management",
    "CRM",
    "practice management",
    "fee-only",
    "RIA",
    "independent advisor",
    "תוכנה פיננסית",
    "ניהול לקוחות",
]

# ---------------------------------------------------------------------------
# Scraping Behaviour
# ---------------------------------------------------------------------------
HEADLESS = True                    # Run Chromium in headless mode
MAX_RESULTS_PER_KEYWORD = 25       # Max profiles to scrape per search keyword
MAX_POSTS_TO_ANALYZE = 5           # Most recent posts to analyse per profile
REQUEST_DELAY_RANGE = (2.0, 5.0)   # Random delay between page actions (seconds)
SCROLL_PAUSE = 1.5                 # Pause after scrolling to load content
PAGE_LOAD_TIMEOUT = 30_000         # ms - Playwright page timeout

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
OUTPUT_DIR = "output"
OUTPUT_CSV = f"{OUTPUT_DIR}/linkedin_leads.csv"
OUTPUT_DB  = f"{OUTPUT_DIR}/linkedin_leads.db"

# CSV columns order
CSV_COLUMNS = [
    "lead_score",
    "name",
    "title",
    "location",
    "connections",
    "profile_url",
    "email",
    "website",
    "about_snippet",
    "posts_analyzed",
    "avg_comments",
    "avg_likes",
    "avg_shares",
    "top_post_url",
    "top_post_comments",
    "keywords_found",
    "scraped_at",
]
