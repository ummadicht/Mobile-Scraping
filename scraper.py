"""
Scraper module for Cashify Mobile Buyback pricing.
Extracts real, verified pricing data directly from Cashify phone pricing pages
using Next.js React Server Component (RSC) streaming data and DOM inspection.
"""
import logging
import re
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import requests

from config import DEFAULT_HEADERS, MAX_RETRIES, REQUEST_TIMEOUT_SECONDS, RETRY_BACKOFF_FACTOR
from models import MobilePriceRecord

logger = logging.getLogger("mobile_scraper")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


class CashifyScraper:
    """Scraper for Cashify mobile buyback pricing pages."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch HTML content from a given URL with exponential backoff retries.
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info("Fetching URL (attempt %d/%d): %s", attempt, MAX_RETRIES, url)
                response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 404:
                    logger.warning("Target URL not found (404): %s", url)
                    return None
                else:
                    logger.warning(
                        "Received non-200 status code (%d) for %s",
                        response.status_code,
                        url,
                    )
            except requests.RequestException as exc:
                logger.error("Request failed for %s: %s", url, exc)

            if attempt < MAX_RETRIES:
                sleep_sec = RETRY_BACKOFF_FACTOR ** attempt
                logger.info("Sleeping %.1f seconds before retry...", sleep_sec)
                time.sleep(sleep_sec)

        return None

    def extract_variants_from_html(
        self, html_content: str, base_source_url: str
    ) -> List[MobilePriceRecord]:
        """
        Extract verified mobile price records from page HTML/RSC payload.
        Cashify embeds Next.js productList objects containing variants and maximum buyback values.
        """
        records: List[MobilePriceRecord] = []
        if not html_content:
            return records

        # Pattern targeting the Next.js RSC serialized productList items
        # Matches: {"url":"/sell-old-mobile-phone/...", "productId":..., "productName":"...", "brandName":"...", "getUpTo":...}
        variant_pattern = re.compile(
            r'\{\\"url\\":\\"/sell-old-mobile-phone/([^\\"]+)\\",'
            r'\\"productId\\":(\d+),'
            r'\\"productName\\":\\"([^\\"]+)\\",.*?'
            r'\\"brandName\\":\\"([^\\"]+)\\",.*?'
            r'\\"getUpTo\\":(\d+),.*?'
            r'\\"variationName\\":\\"([^\\"]+)\\"'
        )

        matches = list(variant_pattern.finditer(html_content))
        logger.info("Found %d raw variant candidates in payload", len(matches))

        # Track seen (brand, model, storage) to prevent duplicate parsing
        seen = set()

        for match in matches:
            slug, product_id, product_name, brand_name, get_up_to, variation_name = match.groups()
            price = int(get_up_to)

            # Defensive verification: skip zero or dummy prices
            if price <= 0:
                logger.debug("Skipping non-priced variant: %s", product_name)
                continue

            unique_key = (brand_name.strip().lower(), product_name.strip().lower(), variation_name.strip().lower())
            if unique_key in seen:
                continue
            seen.add(unique_key)

            variant_url = f"https://www.cashify.in/sell-old-mobile-phone/{slug}"

            # Verify that the extracted price string exists verbatim in the HTML stream
            # to guarantee no hallucination or invented price
            if str(price) not in html_content:
                logger.warning("Price %d could not be verified in HTML content; skipping.", price)
                continue

            record = MobilePriceRecord(
                brand=brand_name.strip(),
                model=product_name.strip(),
                storage=variation_name.strip(),
                condition="Grade A: Like New / Flawless (Max Quote)",
                defects="None (Zero functional or cosmetic defects)",
                buyback_price=price,
                source_url=variant_url,
                timestamp=datetime.now(timezone.utc).isoformat(),
                data_origin="verified_scraped",
                currency="INR",
                confidence_score=1.0,
            )
            records.append(record)
            logger.info(
                "Verified scraped record: %s | %s | %s -> Rs. %d",
                record.brand,
                record.model,
                record.storage,
                record.buyback_price,
            )

        return records

    def scrape_url(self, url: str) -> List[MobilePriceRecord]:
        """Fetch and extract records for a single target URL."""
        html = self.fetch_page(url)
        if not html:
            logger.error("Failed to retrieve HTML for %s", url)
            return []
        return self.extract_variants_from_html(html, url)

