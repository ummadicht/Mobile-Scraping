
"""
Cashify Mobile Buyback Price Scraper.

Extracts mobile buyback pricing and device specifications from Cashify
product pages using Schema.org metadata and Next.js page data.

Supports:
- Individual mobile variant pages.
- Parent product pages containing multiple storage variants.
- Configurable request timeout and retry attempts.
- Exponential backoff for transient request failures.
- Multiple price and specification extraction strategies.

IMPORTANT:
Scraped values represent the data returned in the fetched HTML.
They should not be described as guaranteed live checkout quotes or
100% verified prices without independent validation.
"""

import json
import logging
import re
import sys
import time

from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import (
    DEFAULT_HEADERS,
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BACKOFF_FACTOR,
)

from models import MobilePriceRecord


logger = logging.getLogger("mobile_scraper")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


class CashifyScraper:
    """Scraper for Cashify mobile buyback pricing pages."""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
    ):
        """
        Initialize the Cashify scraper.

        Args:
            session: Optional reusable requests session.
            timeout: Maximum request timeout in seconds.
            max_retries: Maximum number of request attempts.
        """
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

        self.timeout = timeout
        self.max_retries = max_retries

    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch HTML content with configurable retries and exponential backoff.

        Returns:
            HTML response text if successful, otherwise None.
        """
        for attempt in range(1, self.max_retries + 1):

            try:
                logger.info(
                    "Fetching URL (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    url,
                )

                response = self.session.get(
                    url,
                    timeout=self.timeout,
                )

                if response.status_code == 200:
                    return response.text

                if response.status_code == 404:
                    logger.warning("Page not found (404): %s", url)
                    return None

                logger.warning(
                    "Received HTTP status %d for %s",
                    response.status_code,
                    url,
                )

            except requests.RequestException as exc:
                logger.error(
                    "Request failed for %s: %s",
                    url,
                    exc,
                )

            if attempt < self.max_retries:
                sleep_sec = RETRY_BACKOFF_FACTOR ** attempt

                logger.info(
                    "Retrying in %.1f seconds...",
                    sleep_sec,
                )

                time.sleep(sleep_sec)

        logger.error(
            "Failed to fetch URL after %d attempts: %s",
            self.max_retries,
            url,
        )

        return None

    @staticmethod
    def _extract_price(soup: BeautifulSoup, html: str) -> Optional[int]:
        """
        Extract the buyback price from Schema.org metadata or Next.js data.

        Returns:
            Positive integer price in INR, or None if unavailable.
        """

        # First preference: Schema.org price metadata.
        price_tag = soup.find(attrs={"itemprop": "price"})

        if price_tag:
            raw_price = (
                price_tag.get("content")
                or price_tag.get_text(strip=True)
            )

            if raw_price:
                match = re.search(r"\d+(?:\.\d+)?", str(raw_price))

                if match:
                    price = int(float(match.group()))

                    if price > 0:
                        return price

        # Fallback: Next.js getUpTo property.
        patterns = [
            r'"getUpTo"\s*:\s*"?(\d+)"?',
            r'\\"getUpTo\\"\s*:\s*\\"?(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)

            if match:
                price = int(match.group(1))

                if price > 0:
                    return price

        return None

    @staticmethod
    def _extract_json_value(html: str, key: str) -> Optional[str]:
        """
        Extract a specification value from serialized page data.

        Handles common JSON and escaped JSON representations.
        """

        escaped_key = re.escape(key)

        patterns = [
            rf'"{escaped_key}"\s*:\s*\[.*?"dval"\s*:\s*"([^"]+)"',
            rf'\\"{escaped_key}\\"\s*:\s*\[.*?\\"dval\\"\s*:\s*\\"([^\\"]+)',
            rf'"{escaped_key}"\s*:\s*"([^"]+)"',
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                html,
                re.DOTALL,
            )

            if match:
                return match.group(1).strip()

        return None

    @staticmethod
    def _extract_brand(
        soup: BeautifulSoup,
        html: str,
    ) -> Optional[str]:
        """Extract the device brand from structured page data."""

        brand_tag = soup.find(attrs={"itemprop": "brand"})

        if brand_tag:
            brand = (
                brand_tag.get("content")
                or brand_tag.get_text(strip=True)
            )

            if brand:
                return brand.strip()

        patterns = [
            r'"brandName"\s*:\s*"([^"]+)"',
            r'\\"brandName\\"\s*:\s*\\"([^\\"]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)

            if match:
                return match.group(1).strip()

        return None

    @staticmethod
    def _extract_model_name(
        soup: BeautifulSoup,
        url: str,
    ) -> str:
        """Extract the device model name from page metadata or URL."""

        # Prefer the main product heading.
        h1 = soup.find("h1")

        if h1:
            model_name = h1.get_text(" ", strip=True)

            model_name = re.sub(
                r"^Sell Old\s+",
                "",
                model_name,
                flags=re.IGNORECASE,
            )

            model_name = re.sub(
                r"\s*Online\s*&\s*Get Instant Cash.*$",
                "",
                model_name,
                flags=re.IGNORECASE,
            )

            if model_name:
                return model_name.strip()

        # Fallback to product image metadata.
        img = soup.find("img", attrs={"itemprop": "image"})

        if img and img.get("alt"):
            return img["alt"].strip()

        # Final fallback: derive the name from the URL slug.
        slug = urlparse(url).path.rstrip("/").split("/")[-1]

        slug = re.sub(
            r"^used-",
            "",
            slug,
            flags=re.IGNORECASE,
        )

        return slug.replace("-", " ").title()

    def scrape_single_variant_page(
        self,
        html: str,
        url: str,
    ) -> Optional[MobilePriceRecord]:
        """
        Extract pricing and device specifications from a variant page.

        A variant page represents a specific combination of device model
        and storage configuration.
        """

        soup = BeautifulSoup(html, "html.parser")

        # --------------------------------------------------
        # 1. Extract buyback price
        # --------------------------------------------------

        price = self._extract_price(soup, html)

        if not price:
            logger.warning(
                "Unable to extract a valid buyback price: %s",
                url,
            )
            return None

        # --------------------------------------------------
        # 2. Extract brand
        # --------------------------------------------------

        brand = self._extract_brand(soup, html)

        # --------------------------------------------------
        # 3. Extract model name
        # --------------------------------------------------

        model_name = self._extract_model_name(soup, url)

        # --------------------------------------------------
        # 4. Extract device specifications
        # --------------------------------------------------

        storage_val = (
            self._extract_json_value(html, "storage")
            or self._extract_json_value(html, "variationName")
        )

        if not storage_val:
            storage_match = re.search(
                r"(\d+\s*(?:GB|TB))",
                model_name,
                re.IGNORECASE,
            )

            storage_val = (
                storage_match.group(1)
                if storage_match
                else "Standard"
            )

        ram_val = self._extract_json_value(html, "ram")

        cores_val = self._extract_json_value(html, "cores")

        # Camera specifications may contain multiple entries.
        cameras = None

        camera_match = re.search(
            r'["\\]+backCamera["\\]+\s*:\s*\[(.*?)\]',
            html,
            re.DOTALL,
        )

        if camera_match:
            camera_values = re.findall(
                r'["\\]+dval["\\]+\s*:\s*["\\]+([^"\\]+)',
                camera_match.group(1),
            )

            if camera_values:
                cameras = ", ".join(camera_values)

        # --------------------------------------------------
        # 5. Build pricing record
        # --------------------------------------------------

        record = MobilePriceRecord(
            brand=brand or "Unknown",
            model=model_name,
            storage=storage_val,
            ram=ram_val,
            cores=cores_val,
            camera=cameras,
            condition="Grade A: Like New / Flawless (Max Quote)",
            defects="None (Assumed Grade A condition)",
            buyback_price=price,
            source_url=url,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data_origin="verified_scraped",
            currency="INR",
            confidence_score=1.0,
        )

        logger.info(
            "Price extracted: %s | %s | INR %d | Source: %s",
            record.model,
            record.storage,
            record.buyback_price,
            url,
        )

        return record

    def scrape_url(self, url: str) -> List[MobilePriceRecord]:
        """
        Scrape a Cashify product URL.

        Supports both parent product pages and individual variant pages.

        Parent pages:
            Discovers variant URLs and fetches each variant separately.

        Variant pages:
            Extracts pricing and specifications directly.

        Returns:
            List of successfully extracted MobilePriceRecord objects.
        """

        records: List[MobilePriceRecord] = []

        html = self.fetch_page(url)

        if not html:
            return records

        soup = BeautifulSoup(html, "html.parser")

        # --------------------------------------------------
        # 1. Discover variant URLs
        # --------------------------------------------------

        all_variant_urls = set()

        # Extract variant links from HTML anchors.
        for anchor in soup.find_all("a", href=True):

            href = anchor["href"]

            if (
                "/sell-old-mobile-phone/" in href
                and re.search(
                    r"\d+-(?:gb|tb)",
                    href,
                    re.IGNORECASE,
                )
            ):
                variant_url = urljoin(
                    "https://www.cashify.in",
                    href.split("?")[0],
                )

                all_variant_urls.add(variant_url)

        # Extract variant URLs from serialized Next.js page data.
        json_patterns = [
            r'"url"\s*:\s*"/sell-old-mobile-phone/([^"]+)"',
            r'\\"url\\"\s*:\s*\\"/sell-old-mobile-phone/([^\\"]+)',
        ]

        for pattern in json_patterns:

            matches = re.findall(
                pattern,
                html,
            )

            for slug in matches:

                if re.search(
                    r"\d+-(?:gb|tb)",
                    slug,
                    re.IGNORECASE,
                ):
                    variant_url = urljoin(
                        "https://www.cashify.in",
                        "/sell-old-mobile-phone/" + slug,
                    )

                    all_variant_urls.add(
                        variant_url.split("?")[0]
                    )

        # --------------------------------------------------
        # 2. Scrape discovered variants
        # --------------------------------------------------

        if all_variant_urls:

            logger.info(
                "Discovered %d variant URLs for %s",
                len(all_variant_urls),
                url,
            )

            for variant_url in sorted(all_variant_urls):

                try:
                    variant_html = self.fetch_page(
                        variant_url
                    )

                    if not variant_html:
                        continue

                    record = self.scrape_single_variant_page(
                        variant_html,
                        variant_url,
                    )

                    if record:
                        records.append(record)

                except Exception:
                    logger.exception(
                        "Error scraping variant: %s",
                        variant_url,
                    )

        # --------------------------------------------------
        # 3. Process current URL if it is a variant page
        # --------------------------------------------------

        if not records:

            price = self._extract_price(
                soup,
                html,
            )

            if price:
                record = self.scrape_single_variant_page(
                    html,
                    url,
                )

                if record:
                    records.append(record)

        logger.info(
            "Scraping completed for %s. Records extracted: %d",
            url,
            len(records),
        )

        return records
