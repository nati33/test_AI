#!/usr/bin/env python3
"""
GemelNet Data Downloader
========================
Downloads all available gemelnet (pension/provident fund) data from:
1. Israel Open Data Portal (data.gov.il) - CKAN API
2. GemelNet direct XML/CSV exports

Output goes to: ./nati_Ai_test/
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("nati_Ai_test/download.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("nati_Ai_test")
CKAN_API = "https://data.gov.il/api/3/action"
DATASET_ID = "gemelnet"
GEMELNET_BASE = "https://gemelnet.cma.gov.il"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
})


def download_file(url: str, dest: Path, description: str = "") -> bool:
    """Download a file with retry logic."""
    for attempt in range(4):
        try:
            logger.info(f"Downloading: {description or url}")
            resp = SESSION.get(url, timeout=120, stream=True)
            resp.raise_for_status()

            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_kb = dest.stat().st_size / 1024
            logger.info(f"  Saved: {dest} ({size_kb:.1f} KB)")
            return True
        except requests.RequestException as e:
            wait = 2 ** (attempt + 1)
            logger.warning(f"  Attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)

    logger.error(f"  Failed to download: {url}")
    return False


def download_from_ckan():
    """Download all resources from the gemelnet dataset on data.gov.il."""
    logger.info("=" * 60)
    logger.info("PHASE 1: Downloading from Israel Open Data Portal (data.gov.il)")
    logger.info("=" * 60)

    ckan_dir = OUTPUT_DIR / "data_gov_il"
    ckan_dir.mkdir(parents=True, exist_ok=True)

    # Get dataset metadata
    try:
        resp = SESSION.get(
            f"{CKAN_API}/package_show",
            params={"id": DATASET_ID},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch dataset metadata: {e}")
        return

    if not data.get("success"):
        logger.error(f"CKAN API returned error: {data}")
        return

    dataset = data["result"]
    resources = dataset.get("resources", [])
    logger.info(f"Found {len(resources)} resources in dataset '{dataset.get('title', DATASET_ID)}'")

    # Save dataset metadata
    meta_path = ckan_dir / "dataset_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved metadata to {meta_path}")

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
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
        safe_name = safe_name.strip()[:100]
        filename = f"{i:03d}_{safe_name}.{fmt}"
        dest = ckan_dir / filename

        download_file(url, dest, description=f"[{i}/{len(resources)}] {name} ({fmt})")

        # Also try CKAN datastore API for structured data
        if res_id:
            try:
                ds_resp = SESSION.get(
                    f"{CKAN_API}/datastore_search",
                    params={"resource_id": res_id, "limit": 0},
                    timeout=15,
                )
                ds_data = ds_resp.json()
                if ds_data.get("success"):
                    total = ds_data["result"].get("total", 0)
                    if total > 0:
                        logger.info(f"  Datastore has {total} records, downloading CSV dump...")
                        csv_url = f"https://data.gov.il/api/3/action/datastore_search?resource_id={res_id}&limit={total}"
                        csv_dest = ckan_dir / f"{i:03d}_{safe_name}_full_data.json"
                        download_file(csv_url, csv_dest, f"  Full datastore dump ({total} records)")
            except Exception:
                pass  # Datastore not available for this resource


def download_from_gemelnet_direct():
    """Try to download data directly from GemelNet website."""
    logger.info("=" * 60)
    logger.info("PHASE 2: Downloading directly from GemelNet")
    logger.info("=" * 60)

    gemel_dir = OUTPUT_DIR / "gemelnet_direct"
    gemel_dir.mkdir(parents=True, exist_ok=True)

    # Save the main page
    try:
        resp = SESSION.get(f"{GEMELNET_BASE}/views/dafmakdim.aspx", timeout=30)
        resp.raise_for_status()
        with open(gemel_dir / "dafmakdim.html", "wb") as f:
            f.write(resp.content)
        logger.info("Saved main page (dafmakdim.aspx)")
    except Exception as e:
        logger.warning(f"Could not fetch main page: {e}")

    # Known GemelNet data pages and endpoints
    known_pages = [
        "/views/dafMakdim_Link1.aspx",
        "/views/dafMakdim_Link4.aspx",
        "/views/horadatXML.aspx",
        "/views/Bitul.aspx",
        "/views/tasua.aspx",
        "/views/dmeyNihul.aspx",
        "/views/NetuneyYesod.aspx",
        "/views/tpisat_kupot.aspx",
    ]

    for page in known_pages:
        try:
            url = f"{GEMELNET_BASE}{page}"
            resp = SESSION.get(url, timeout=30)
            if resp.status_code == 200:
                fname = page.split("/")[-1]
                with open(gemel_dir / fname, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Saved {fname}")
        except Exception as e:
            logger.warning(f"Could not fetch {page}: {e}")

    # Try XML export endpoint (used by the site's AJAX calls)
    # The site uses funcXML_display_shm_OCHLUSIYA() to fetch XML data
    xml_endpoints = [
        "/Handlers/XMLHandler.ashx",
        "/api/export",
        "/handlers/ExportToExcel.ashx",
    ]

    for endpoint in xml_endpoints:
        try:
            url = f"{GEMELNET_BASE}{endpoint}"
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 100:
                fname = endpoint.split("/")[-1]
                with open(gemel_dir / fname, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Saved {fname}")
        except Exception:
            pass

    # Try to get fund list and data for common fund types
    fund_types = {
        "1": "gemel",       # קופות גמל
        "2": "hishtalmut",   # קרנות השתלמות
        "3": "pensia",       # פנסיה
        "4": "bituach",      # ביטוח
    }

    for type_id, type_name in fund_types.items():
        try:
            # Try common API patterns used by Israeli government sites
            resp = SESSION.post(
                f"{GEMELNET_BASE}/Services/GemelnetService.asmx/GetKupotList",
                json={"sugKupa": type_id},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                dest = gemel_dir / f"kupot_list_{type_name}.json"
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                logger.info(f"Saved fund list for {type_name}")
        except Exception:
            pass


def download_pensianet_data():
    """Try to download from PensiaNet (related CMA resource)."""
    logger.info("=" * 60)
    logger.info("PHASE 3: Attempting PensiaNet export")
    logger.info("=" * 60)

    pensia_dir = OUTPUT_DIR / "pensianet"
    pensia_dir.mkdir(parents=True, exist_ok=True)

    # PensiaNet XML export endpoint
    try:
        resp = SESSION.post(
            "https://pensyanet.cma.gov.il/Parameters/ExportToXML",
            data={"vm": json.dumps({"ReportType": 1})},
            timeout=60,
        )
        if resp.status_code == 200 and len(resp.content) > 100:
            with open(pensia_dir / "pensianet_export.xml", "wb") as f:
                f.write(resp.content)
            logger.info("Saved PensiaNet export")
    except Exception as e:
        logger.warning(f"PensiaNet export failed: {e}")


def create_readme():
    """Create a README explaining the downloaded data."""
    readme = OUTPUT_DIR / "README.txt"
    with open(readme, "w", encoding="utf-8") as f:
        f.write("""GemelNet Data Download
======================
Source: https://gemelnet.cma.gov.il/views/dafmakdim.aspx
Dataset: https://data.gov.il/dataset/gemelnet

This folder contains data from Israel's Capital Market Authority (CMA)
GemelNet system - pension and provident fund data.

Folder structure:
  data_gov_il/     - Data from Israel Open Data Portal (CKAN API)
  gemelnet_direct/ - Pages and data from GemelNet website directly
  pensianet/       - Data from PensiaNet (related CMA system)

Data includes:
  - Monthly reports of provident fund tracks
  - Fund performance data (tasua/returns)
  - Management fees (dmey nihul)
  - Fund basic data (netunei yesod)
  - Fund distribution data (tfisat kupot)

For more information:
  https://gemelnet.cma.gov.il/views/dafMakdim_Link1.aspx
  https://gemelnet.cma.gov.il/views/dafMakdim_Link4.aspx
""")
    logger.info(f"Created {readme}")


def main():
    logger.info("GemelNet Data Downloader")
    logger.info(f"Output directory: {OUTPUT_DIR.resolve()}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    create_readme()
    download_from_ckan()
    download_from_gemelnet_direct()
    download_pensianet_data()

    logger.info("=" * 60)
    logger.info("Download complete!")
    logger.info(f"All data saved to: {OUTPUT_DIR.resolve()}")

    # Summary
    total_files = sum(1 for _ in OUTPUT_DIR.rglob("*") if _.is_file())
    total_size = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
    logger.info(f"Total files: {total_files}")
    logger.info(f"Total size: {total_size / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
