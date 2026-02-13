#!/usr/bin/env python3
"""
GemelNet Data Scraper
=====================
Comprehensive scraper for Israel's Capital Market Authority (CMA) GemelNet system.
Downloads pension/provident fund data from multiple sources:

1. GemelNet XML API - Monthly portfolio data and performance reports
2. Israel Open Data Portal (data.gov.il) - CKAN API dataset
3. GemelNet website pages - ASP.NET pages with fund information

Data sources:
  - XML API: http://gemelnet.cma.gov.il/tsuot/ui/tsuotHodXML.aspx
  - CKAN:    https://data.gov.il/dataset/gemelnet
  - Website: https://gemelnet.cma.gov.il/views/

Output goes to: ./gemelnet_data/
"""

import os
import sys
import csv
import json
import time
import logging
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
import pandas as pd
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("gemelnet_data")

GEMELNET_XML_API = "https://gemelnet.cma.gov.il/tsuot/ui/tsuotHodXML.aspx"
GEMELNET_BASE = "https://gemelnet.cma.gov.il"
CKAN_API = "https://data.gov.il/api/3/action"
DATASET_ID = "gemelnet"

# sug parameter values for the XML API
SUG_PERFORMANCE = 3   # תשואות - performance/returns data
SUG_PORTFOLIO = 4     # פירוט מלא - full portfolio details

# Maximum retries for HTTP requests
MAX_RETRIES = 4

# Delay between batch requests (seconds) - be respectful to the server
REQUEST_DELAY = 0.5

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gemelnet_scraper")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        output_dir / "scraper.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging(OUTPUT_DIR)

# ---------------------------------------------------------------------------
# HTTP Session
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})


def request_with_retry(method, url, retries=MAX_RETRIES, **kwargs):
    """Make an HTTP request with exponential backoff retry logic."""
    kwargs.setdefault("timeout", 120)
    for attempt in range(retries):
        try:
            resp = SESSION.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            logger.warning(
                f"  Request failed (attempt {attempt + 1}/{retries}): {e}. "
                f"Retrying in {wait}s..."
            )
            time.sleep(wait)


# =========================================================================
# Phase 1: GemelNet XML API - Core Data Extraction
# =========================================================================

def parse_xml_rows(xml_text: str) -> list[dict]:
    """Parse GemelNet XML response into a list of dictionaries (one per Row)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"  Failed to parse XML: {e}")
        return []

    rows = []
    for row in root.iter("Row"):
        row_dict = {field.tag: field.text for field in row}
        rows.append(row_dict)
    return rows


def fetch_xml_data(kupa_id, period_from, period_to, sug=SUG_PORTFOLIO):
    """
    Fetch data from the GemelNet XML API.

    Args:
        kupa_id: Fund ID (numeric string, "0000" for all funds)
        period_from: Start period in YYYYMM format
        period_to: End period in YYYYMM format
        sug: Report type (3=performance, 4=full portfolio)

    Returns:
        List of dicts, one per XML Row element.
    """
    params = {
        "miTkfDivuach": period_from,
        "adTkfDivuach": period_to,
        "kupot": kupa_id,
        "Dochot": 1,
        "sug": sug,
    }

    try:
        resp = request_with_retry("GET", GEMELNET_XML_API, params=params)
        resp.encoding = "UTF-8"
    except requests.RequestException as e:
        logger.error(f"  XML API request failed for kupa {kupa_id}: {e}")
        return []

    if not resp.text or len(resp.text.strip()) < 50:
        logger.warning(f"  Empty or minimal response for kupa {kupa_id}")
        return []

    return parse_xml_rows(resp.text)


def save_rows_to_csv(rows: list[dict], filepath: Path, fieldnames=None):
    """Save a list of dicts to a CSV file with BOM for Excel Hebrew support."""
    if not rows:
        return False

    if fieldnames is None:
        fieldnames = list(rows[0].keys())

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"  Saved {len(rows)} rows to {filepath}")
    return True


def download_portfolio_data(kupa_ids: list[str], year: int, month: int):
    """
    Download monthly portfolio data (sug=4) for a list of fund IDs.
    Portfolio data includes detailed asset holdings.
    """
    portfolio_dir = OUTPUT_DIR / "xml_portfolio"
    portfolio_dir.mkdir(parents=True, exist_ok=True)

    period = f"{year:04d}{month:02d}"
    all_rows = []
    success_count = 0

    for i, kupa_id in enumerate(kupa_ids, 1):
        logger.info(
            f"  [{i}/{len(kupa_ids)}] Fetching portfolio for kupa {kupa_id} "
            f"({period})"
        )
        rows = fetch_xml_data(kupa_id, period, period, sug=SUG_PORTFOLIO)

        if rows:
            # Add kupa_id and period context to each row
            for row in rows:
                row["KUPA_ID"] = kupa_id
                row["QUERY_PERIOD"] = period

            # Save individual fund file
            filepath = portfolio_dir / f"{kupa_id}_{period}_portfolio.csv"
            save_rows_to_csv(rows, filepath)
            all_rows.extend(rows)
            success_count += 1

        time.sleep(REQUEST_DELAY)

    # Save combined file
    if all_rows:
        combined_path = portfolio_dir / f"all_portfolio_{period}.csv"
        save_rows_to_csv(all_rows, combined_path)
        logger.info(
            f"Portfolio download complete: {success_count}/{len(kupa_ids)} "
            f"funds, {len(all_rows)} total rows"
        )

    return all_rows


def download_performance_data(
    kupa_ids: list[str],
    from_year: int,
    from_month: int,
    to_year: int,
    to_month: int,
):
    """
    Download performance/returns data (sug=3) for a list of fund IDs.
    Performance data includes monthly returns and net asset values.
    """
    perf_dir = OUTPUT_DIR / "xml_performance"
    perf_dir.mkdir(parents=True, exist_ok=True)

    period_from = f"{from_year:04d}{from_month:02d}"
    period_to = f"{to_year:04d}{to_month:02d}"
    all_rows = []
    success_count = 0

    for i, kupa_id in enumerate(kupa_ids, 1):
        logger.info(
            f"  [{i}/{len(kupa_ids)}] Fetching performance for kupa {kupa_id} "
            f"({period_from}-{period_to})"
        )
        rows = fetch_xml_data(
            kupa_id, period_from, period_to, sug=SUG_PERFORMANCE
        )

        if rows:
            for row in rows:
                row["KUPA_ID"] = kupa_id

            filepath = (
                perf_dir
                / f"{kupa_id}_perf_{period_from}_{period_to}.csv"
            )
            save_rows_to_csv(rows, filepath)
            all_rows.extend(rows)
            success_count += 1

        time.sleep(REQUEST_DELAY)

    # Save combined file
    if all_rows:
        combined_path = (
            perf_dir / f"all_performance_{period_from}_{period_to}.csv"
        )
        save_rows_to_csv(all_rows, combined_path)
        logger.info(
            f"Performance download complete: {success_count}/{len(kupa_ids)} "
            f"funds, {len(all_rows)} total rows"
        )

    return all_rows


def download_all_funds_data(period_from: str, period_to: str):
    """
    Try downloading data for ALL funds at once using kupot=0000.
    This may return a very large dataset.
    """
    logger.info(
        f"Attempting bulk download for all funds ({period_from} to {period_to})"
    )
    bulk_dir = OUTPUT_DIR / "xml_bulk"
    bulk_dir.mkdir(parents=True, exist_ok=True)

    for sug, label in [(SUG_PERFORMANCE, "performance"), (SUG_PORTFOLIO, "portfolio")]:
        logger.info(f"  Fetching bulk {label} data (sug={sug})...")
        rows = fetch_xml_data("0000", period_from, period_to, sug=sug)

        if rows:
            filepath = bulk_dir / f"all_funds_{label}_{period_from}_{period_to}.csv"
            save_rows_to_csv(rows, filepath)

            # Also save raw XML for archival
            try:
                params = {
                    "miTkfDivuach": period_from,
                    "adTkfDivuach": period_to,
                    "kupot": "0000",
                    "Dochot": 1,
                    "sug": sug,
                }
                resp = request_with_retry("GET", GEMELNET_XML_API, params=params)
                resp.encoding = "UTF-8"
                xml_path = bulk_dir / f"all_funds_{label}_{period_from}_{period_to}.xml"
                xml_path.write_text(resp.text, encoding="utf-8")
                logger.info(f"  Saved raw XML to {xml_path}")
            except requests.RequestException:
                pass
        else:
            logger.warning(f"  No bulk {label} data returned")


# =========================================================================
# Phase 2: CKAN API - Israel Open Data Portal
# =========================================================================

def download_from_ckan():
    """Download all resources from the gemelnet dataset on data.gov.il."""
    logger.info("=" * 60)
    logger.info("PHASE 2: Downloading from Israel Open Data Portal (data.gov.il)")
    logger.info("=" * 60)

    ckan_dir = OUTPUT_DIR / "ckan_data"
    ckan_dir.mkdir(parents=True, exist_ok=True)

    # Get dataset metadata
    try:
        resp = request_with_retry(
            "GET", f"{CKAN_API}/package_show", params={"id": DATASET_ID}
        )
        data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch dataset metadata: {e}")
        return []

    if not data.get("success"):
        logger.error(f"CKAN API returned error: {data}")
        return []

    dataset = data["result"]
    resources = dataset.get("resources", [])
    logger.info(
        f"Found {len(resources)} resources in dataset "
        f"'{dataset.get('title', DATASET_ID)}'"
    )

    # Save dataset metadata
    meta_path = ckan_dir / "dataset_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved metadata to {meta_path}")

    kupa_ids_found = set()

    # Download each resource
    for i, resource in enumerate(resources, 1):
        name = resource.get("name") or resource.get("description") or f"resource_{i}"
        fmt = resource.get("format", "").lower() or "dat"
        url = resource.get("url")
        res_id = resource.get("id", "")

        if not url:
            logger.warning(f"  Resource '{name}' has no URL, skipping")
            continue

        # Clean filename
        safe_name = "".join(
            c if c.isalnum() or c in "-_ " else "_" for c in name
        )
        safe_name = safe_name.strip()[:100]
        filename = f"{i:03d}_{safe_name}.{fmt}"
        dest = ckan_dir / filename

        try:
            logger.info(
                f"  [{i}/{len(resources)}] Downloading {name} ({fmt})..."
            )
            resp = request_with_retry("GET", url, stream=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            size_kb = dest.stat().st_size / 1024
            logger.info(f"    Saved: {dest} ({size_kb:.1f} KB)")
        except requests.RequestException as e:
            logger.warning(f"    Failed to download {name}: {e}")
            continue

        # Try CKAN datastore API for structured data
        if res_id:
            try:
                ds_resp = request_with_retry(
                    "GET",
                    f"{CKAN_API}/datastore_search",
                    params={"resource_id": res_id, "limit": 5},
                )
                ds_data = ds_resp.json()
                if ds_data.get("success"):
                    total = ds_data["result"].get("total", 0)
                    fields = ds_data["result"].get("fields", [])

                    if total > 0:
                        logger.info(
                            f"    Datastore has {total} records, "
                            f"{len(fields)} fields"
                        )

                        # Save field info
                        fields_path = ckan_dir / f"{i:03d}_{safe_name}_fields.json"
                        with open(fields_path, "w", encoding="utf-8") as f:
                            json.dump(fields, f, ensure_ascii=False, indent=2)

                        # Download full data in chunks
                        all_records = []
                        chunk_size = 10000
                        offset = 0
                        while offset < total:
                            chunk_resp = request_with_retry(
                                "GET",
                                f"{CKAN_API}/datastore_search",
                                params={
                                    "resource_id": res_id,
                                    "limit": chunk_size,
                                    "offset": offset,
                                },
                            )
                            chunk_data = chunk_resp.json()
                            if chunk_data.get("success"):
                                records = chunk_data["result"].get("records", [])
                                all_records.extend(records)
                                offset += chunk_size
                                logger.info(
                                    f"    Fetched {min(offset, total)}/{total} records"
                                )
                            else:
                                break

                        if all_records:
                            # Save as CSV via pandas
                            df = pd.DataFrame(all_records)
                            csv_path = ckan_dir / f"{i:03d}_{safe_name}_data.csv"
                            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                            logger.info(
                                f"    Saved {len(all_records)} records to {csv_path}"
                            )

                            # Extract kupa IDs if available
                            for col in ["KUPA_ID", "kupa_id", "KupaId", "kupot"]:
                                if col in df.columns:
                                    kupa_ids_found.update(
                                        df[col].dropna().astype(str).unique()
                                    )
            except Exception:
                pass  # Datastore not available for this resource

    return sorted(kupa_ids_found)


# =========================================================================
# Phase 3: GemelNet Website Scraping
# =========================================================================

def scrape_gemelnet_pages():
    """
    Scrape HTML pages from the GemelNet website to extract
    fund lists, links, and any embedded data tables.
    """
    logger.info("=" * 60)
    logger.info("PHASE 3: Scraping GemelNet website pages")
    logger.info("=" * 60)

    pages_dir = OUTPUT_DIR / "website_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Known GemelNet pages
    pages = {
        "dafmakdim.aspx": "דף מקדים - Landing page",
        "dafMakdim_Link1.aspx": "מה ניתן להפיק - What can be produced",
        "dafMakdim_Link3.aspx": "מקורות מידע - Data sources",
        "dafMakdim_Link4.aspx": "הגדרות - Definitions",
        "dafMakdim_Link5.aspx": "הסברים - Explanations",
        "horadatXML.aspx": "הורדת XML - XML download page",
        "tasua.aspx": "תשואה - Returns/Performance",
        "dmeyNihul.aspx": "דמי ניהול - Management fees",
        "NetuneyYesod.aspx": "נתוני יסוד - Basic fund data",
        "tpisat_kupot.aspx": "תפיסת קופות - Fund distribution",
        "Bitul.aspx": "ביטול - Cancellation",
    }

    kupa_ids_from_pages = set()

    for page_name, description in pages.items():
        url = f"{GEMELNET_BASE}/views/{page_name}"
        try:
            logger.info(f"  Fetching {page_name} ({description})...")
            resp = request_with_retry("GET", url)

            # Save raw HTML
            html_path = pages_dir / page_name.replace(".aspx", ".html")
            html_path.write_bytes(resp.content)
            logger.info(f"    Saved to {html_path}")

            # Parse and extract data tables
            soup = BeautifulSoup(resp.content, "lxml")
            tables = soup.find_all("table")
            if tables:
                logger.info(f"    Found {len(tables)} tables in {page_name}")

                for t_idx, table in enumerate(tables):
                    rows_data = extract_html_table(table)
                    if rows_data and len(rows_data) > 1:
                        table_path = (
                            pages_dir
                            / f"{page_name.replace('.aspx', '')}_table_{t_idx}.csv"
                        )
                        save_rows_to_csv(rows_data, table_path)

            # Extract any kupa IDs from links/forms
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "kupot=" in href or "idGuf=" in href:
                    # Extract numeric IDs from URL parameters
                    for param in href.split("&"):
                        if "kupot=" in param or "idGuf=" in param:
                            val = param.split("=")[-1]
                            if val.isdigit():
                                kupa_ids_from_pages.add(val)

            # Extract from select/option elements (dropdown menus)
            for select in soup.find_all("select"):
                select_name = select.get("name", select.get("id", "unknown"))
                options = []
                for option in select.find_all("option"):
                    val = option.get("value", "")
                    text = option.get_text(strip=True)
                    if val:
                        options.append({"value": val, "text": text})
                        if val.isdigit() and len(val) >= 2:
                            kupa_ids_from_pages.add(val)

                if options:
                    options_path = (
                        pages_dir
                        / f"{page_name.replace('.aspx', '')}_{select_name}_options.json"
                    )
                    with open(options_path, "w", encoding="utf-8") as f:
                        json.dump(options, f, ensure_ascii=False, indent=2)
                    logger.info(
                        f"    Saved {len(options)} options from dropdown "
                        f"'{select_name}'"
                    )

        except requests.RequestException as e:
            logger.warning(f"    Failed to fetch {page_name}: {e}")
        except Exception as e:
            logger.warning(f"    Error processing {page_name}: {e}")

        time.sleep(REQUEST_DELAY)

    # Try known dynamic pages with parameters
    ochlusiya_types = {
        "1": "gemel",        # קופות גמל
        "2": "hishtalmut",   # קרנות השתלמות
        "3": "pensia",       # פנסיה
        "4": "bituach",      # ביטוח
    }

    for och_id, och_name in ochlusiya_types.items():
        # Try perutHodshi (monthly details) for different institution IDs
        for guf_id in ["30", "110", "1", "5", "10", "15", "20", "50"]:
            url = (
                f"{GEMELNET_BASE}/views/perutHodshi.aspx"
                f"?idGuf={guf_id}&OCHLUSIYA={och_id}"
            )
            try:
                resp = request_with_retry("GET", url)
                if resp.status_code == 200 and len(resp.content) > 500:
                    soup = BeautifulSoup(resp.content, "lxml")
                    tables = soup.find_all("table")
                    for t_idx, table in enumerate(tables):
                        rows_data = extract_html_table(table)
                        if rows_data and len(rows_data) > 1:
                            filepath = (
                                pages_dir
                                / f"perutHodshi_guf{guf_id}_{och_name}_table{t_idx}.csv"
                            )
                            save_rows_to_csv(rows_data, filepath)
                    logger.info(
                        f"    Saved perutHodshi for guf={guf_id}, "
                        f"ochlusiya={och_name}"
                    )
            except Exception:
                pass
            time.sleep(REQUEST_DELAY)

    return sorted(kupa_ids_from_pages)


def extract_html_table(table) -> list[dict]:
    """Extract data from an HTML table element into a list of dicts."""
    rows = table.find_all("tr")
    if not rows:
        return []

    # Find header row
    headers = []
    data_start = 0
    for i, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        texts = [cell.get_text(strip=True) for cell in cells]
        if any(texts):
            if row.find_all("th") or i == 0:
                headers = texts
                data_start = i + 1
                break

    if not headers:
        return []

    # Extract data rows
    result = []
    for row in rows[data_start:]:
        cells = row.find_all("td")
        if len(cells) >= len(headers):
            row_dict = {}
            for j, header in enumerate(headers):
                if header:
                    row_dict[header] = cells[j].get_text(strip=True)
            if any(row_dict.values()):
                result.append(row_dict)

    return result


# =========================================================================
# Phase 4: PensiaNet Export
# =========================================================================

def download_pensianet_data():
    """Download data from PensiaNet (related CMA pension system)."""
    logger.info("=" * 60)
    logger.info("PHASE 4: Downloading PensiaNet data")
    logger.info("=" * 60)

    pensia_dir = OUTPUT_DIR / "pensianet"
    pensia_dir.mkdir(parents=True, exist_ok=True)

    # PensiaNet XML export - try multiple report types
    for report_type in [1, 2, 3, 4]:
        try:
            logger.info(f"  Trying PensiaNet export (ReportType={report_type})...")
            resp = request_with_retry(
                "POST",
                "https://pensyanet.cma.gov.il/Parameters/ExportToXML",
                data={"vm": json.dumps({"ReportType": report_type})},
                timeout=60,
            )
            if resp.status_code == 200 and len(resp.content) > 100:
                xml_path = pensia_dir / f"pensianet_report_{report_type}.xml"
                xml_path.write_bytes(resp.content)
                logger.info(f"    Saved PensiaNet report type {report_type}")

                # Try to parse as XML and convert to CSV
                try:
                    rows = parse_xml_rows(resp.text)
                    if rows:
                        csv_path = pensia_dir / f"pensianet_report_{report_type}.csv"
                        save_rows_to_csv(rows, csv_path)
                except Exception:
                    pass  # XML format may differ
        except Exception as e:
            logger.warning(f"    PensiaNet report {report_type} failed: {e}")


# =========================================================================
# Fund Discovery - Finding all available kupa IDs
# =========================================================================

def discover_fund_ids() -> list[str]:
    """
    Try to discover all available fund IDs from multiple sources.
    Returns a sorted list of unique fund IDs.
    """
    logger.info("=" * 60)
    logger.info("Discovering available fund IDs...")
    logger.info("=" * 60)

    fund_ids = set()

    # Method 1: Try bulk query with kupot=0000 for recent month
    now = datetime.now()
    # Use previous month as data may not yet be available for current month
    prev_month = now.replace(day=1) - timedelta(days=1)
    period = f"{prev_month.year:04d}{prev_month.month:02d}"

    logger.info(f"  Trying bulk query for period {period}...")
    try:
        resp = request_with_retry(
            "GET",
            GEMELNET_XML_API,
            params={
                "miTkfDivuach": period,
                "adTkfDivuach": period,
                "kupot": "0000",
                "Dochot": 1,
                "sug": SUG_PERFORMANCE,
            },
        )
        resp.encoding = "UTF-8"
        rows = parse_xml_rows(resp.text)
        for row in rows:
            for key in ["KUPA_ID", "MISPAR_KUPA", "ID_KUPA", "kupot"]:
                if key in row and row[key]:
                    fund_ids.add(row[key])
        if fund_ids:
            logger.info(f"  Found {len(fund_ids)} fund IDs from bulk query")
    except Exception as e:
        logger.warning(f"  Bulk query failed: {e}")

    # Method 2: Try common fund ID ranges (known Israeli fund ID patterns)
    # Israeli fund IDs typically range from 1 to about 10000
    if not fund_ids:
        logger.info("  Probing common fund ID ranges...")
        # Test a sample of IDs to find valid ranges
        test_ids = list(range(1, 201)) + list(range(500, 601)) + list(range(1000, 1201))
        for test_id in test_ids:
            try:
                resp = request_with_retry(
                    "GET",
                    GEMELNET_XML_API,
                    params={
                        "miTkfDivuach": period,
                        "adTkfDivuach": period,
                        "kupot": str(test_id),
                        "Dochot": 1,
                        "sug": SUG_PERFORMANCE,
                    },
                    retries=1,
                )
                resp.encoding = "UTF-8"
                if resp.text and "<Row>" in resp.text:
                    fund_ids.add(str(test_id))
            except Exception:
                pass

            # Don't hammer the server
            if test_ids.index(test_id) % 50 == 0:
                time.sleep(1)

        if fund_ids:
            logger.info(f"  Found {len(fund_ids)} valid fund IDs from probing")

    # Method 3: Get from CKAN metadata
    try:
        resp = request_with_retry(
            "GET", f"{CKAN_API}/package_show", params={"id": DATASET_ID}
        )
        data = resp.json()
        if data.get("success"):
            resources = data["result"].get("resources", [])
            for resource in resources:
                res_id = resource.get("id", "")
                if res_id:
                    try:
                        ds_resp = request_with_retry(
                            "GET",
                            f"{CKAN_API}/datastore_search",
                            params={"resource_id": res_id, "limit": 100},
                        )
                        ds_data = ds_resp.json()
                        if ds_data.get("success"):
                            for record in ds_data["result"].get("records", []):
                                for col in [
                                    "KUPA_ID", "kupa_id", "KupaId",
                                    "MISPAR_KUPA",
                                ]:
                                    if col in record and record[col]:
                                        fund_ids.add(str(record[col]))
                    except Exception:
                        pass
    except Exception:
        pass

    result = sorted(fund_ids, key=lambda x: int(x) if x.isdigit() else 0)
    logger.info(f"Total unique fund IDs discovered: {len(result)}")

    # Save discovered IDs
    ids_path = OUTPUT_DIR / "discovered_fund_ids.json"
    with open(ids_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved fund IDs to {ids_path}")

    return result


# =========================================================================
# Main Orchestration
# =========================================================================

def create_summary(start_time: float):
    """Create a summary of all downloaded data."""
    elapsed = time.time() - start_time

    summary_lines = [
        "GemelNet Data Scraper - Summary",
        "=" * 40,
        f"Run completed at: {datetime.now().isoformat()}",
        f"Duration: {elapsed:.0f} seconds",
        "",
        "Downloaded data structure:",
    ]

    total_files = 0
    total_size = 0
    for subdir in sorted(OUTPUT_DIR.iterdir()):
        if subdir.is_dir():
            files = list(subdir.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            dir_size = sum(f.stat().st_size for f in files if f.is_file())
            total_files += file_count
            total_size += dir_size
            summary_lines.append(
                f"  {subdir.name}/: {file_count} files "
                f"({dir_size / 1024:.1f} KB)"
            )

    summary_lines.extend([
        "",
        f"Total files: {total_files}",
        f"Total size: {total_size / 1024 / 1024:.2f} MB",
        "",
        "Data sources:",
        f"  XML API:  {GEMELNET_XML_API}",
        f"  CKAN:     https://data.gov.il/dataset/{DATASET_ID}",
        f"  Website:  {GEMELNET_BASE}/views/dafmakdim.aspx",
        "",
        "File formats:",
        "  .csv  - Tabular data (UTF-8 with BOM for Excel compatibility)",
        "  .xml  - Raw XML responses from GemelNet API",
        "  .html - Saved web pages",
        "  .json - Metadata and structured data",
    ])

    summary_text = "\n".join(summary_lines)
    summary_path = OUTPUT_DIR / "SUMMARY.txt"
    summary_path.write_text(summary_text, encoding="utf-8")

    logger.info("\n" + summary_text)
    return summary_text


def main():
    parser = argparse.ArgumentParser(
        description="GemelNet Data Scraper - Download pension fund data from CMA"
    )
    parser.add_argument(
        "--period-from",
        type=str,
        default=None,
        help="Start period in YYYYMM format (default: 12 months ago)",
    )
    parser.add_argument(
        "--period-to",
        type=str,
        default=None,
        help="End period in YYYYMM format (default: last month)",
    )
    parser.add_argument(
        "--kupa-ids",
        type=str,
        nargs="*",
        default=None,
        help="Specific fund IDs to download (default: auto-discover)",
    )
    parser.add_argument(
        "--skip-ckan",
        action="store_true",
        help="Skip CKAN data portal download",
    )
    parser.add_argument(
        "--skip-website",
        action="store_true",
        help="Skip website page scraping",
    )
    parser.add_argument(
        "--skip-pensianet",
        action="store_true",
        help="Skip PensiaNet export",
    )
    parser.add_argument(
        "--skip-xml",
        action="store_true",
        help="Skip XML API data download",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: ./gemelnet_data)",
    )
    parser.add_argument(
        "--bulk-only",
        action="store_true",
        help="Only do bulk download (kupot=0000) instead of per-fund",
    )

    args = parser.parse_args()

    # Update output directory if specified
    global OUTPUT_DIR
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    logger.info("=" * 60)
    logger.info("GemelNet Data Scraper")
    logger.info(f"Output directory: {OUTPUT_DIR.resolve()}")
    logger.info("=" * 60)

    # Calculate default date range (last 12 months)
    now = datetime.now()
    prev_month = now.replace(day=1) - timedelta(days=1)

    if args.period_to:
        period_to = args.period_to
    else:
        period_to = f"{prev_month.year:04d}{prev_month.month:02d}"

    if args.period_from:
        period_from = args.period_from
    else:
        from_date = prev_month - timedelta(days=365)
        period_from = f"{from_date.year:04d}{from_date.month:02d}"

    logger.info(f"Date range: {period_from} to {period_to}")

    # --- Phase 1: XML API ---
    if not args.skip_xml:
        logger.info("=" * 60)
        logger.info("PHASE 1: GemelNet XML API Data Download")
        logger.info("=" * 60)

        # First try bulk download
        download_all_funds_data(period_from, period_to)

        if not args.bulk_only:
            # Discover or use provided fund IDs
            if args.kupa_ids:
                kupa_ids = args.kupa_ids
            else:
                kupa_ids = discover_fund_ids()

            if kupa_ids:
                # Download per-fund data for a single recent month
                # (full range per-fund would be too many requests)
                download_portfolio_data(
                    kupa_ids[:200],  # Limit to first 200 for initial run
                    prev_month.year,
                    prev_month.month,
                )
                download_performance_data(
                    kupa_ids[:200],
                    int(period_from[:4]),
                    int(period_from[4:6]),
                    int(period_to[:4]),
                    int(period_to[4:6]),
                )
            else:
                logger.warning("No fund IDs discovered, skipping per-fund download")

    # --- Phase 2: CKAN ---
    if not args.skip_ckan:
        ckan_kupa_ids = download_from_ckan()
        if ckan_kupa_ids:
            logger.info(f"Found {len(ckan_kupa_ids)} fund IDs from CKAN data")

    # --- Phase 3: Website ---
    if not args.skip_website:
        page_kupa_ids = scrape_gemelnet_pages()
        if page_kupa_ids:
            logger.info(
                f"Found {len(page_kupa_ids)} fund IDs from website pages"
            )

    # --- Phase 4: PensiaNet ---
    if not args.skip_pensianet:
        download_pensianet_data()

    # --- Summary ---
    create_summary(start_time)

    logger.info("=" * 60)
    logger.info("Scraping complete!")
    logger.info(f"All data saved to: {OUTPUT_DIR.resolve()}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
