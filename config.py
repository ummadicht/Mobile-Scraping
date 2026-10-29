"""
Configuration module for Refurbished Mobile Price Intelligence System.
Centralizes scraping targets, HTTP parameters, grading multipliers, and file paths.
"""
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON_PATH = BASE_DIR / "output.json"
OUTPUT_CSV_PATH = BASE_DIR / "output.csv"

# Target Mobile Buyback URLs (Cashify authorized public pricing pages)
TARGET_DEVICES = [
    {
        "brand": "Apple",
        "model_family": "iPhone 13",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-apple-iphone-13",
    },
    {
        "brand": "Apple",
        "model_family": "iPhone 12",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-apple-iphone-12",
    },
    {
        "brand": "Apple",
        "model_family": "iPhone 11",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-apple-iphone-11",
    },
    {
        "brand": "Apple",
        "model_family": "iPhone 14",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-apple-iphone-14",
    },
    {
        "brand": "Samsung",
        "model_family": "Galaxy S21 5G",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-samsung-galaxy-s21-5g",
    },
    {
        "brand": "Samsung",
        "model_family": "Galaxy S23 5G",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-samsung-galaxy-s23-5g",
    },
    {
        "brand": "Samsung",
        "model_family": "Galaxy Note 20",
        "url": "https://www.cashify.in/sell-old-mobile-phone/used-samsung-galaxy-note-20-8-gb-256-gb",
    },
]

# HTTP Request Headers
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
}

# Network settings
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 1.5

# Condition and Defect Grading Multipliers (Industry standard buyback benchmarks)
# Used to simulate condition tiers against verified live maximum buyback baseline
CONDITION_TIERS = {
    "Grade A (Flawless)": {
        "condition_desc": "Like New / Flawless - 100% functional, zero scratches, battery health > 85%",
        "defects": "None",
        "factor": 1.00,
    },
    "Grade B (Good)": {
        "condition_desc": "Good - Fully functional, minor hairline scratches on body/frame, no dents",
        "defects": "Minor cosmetic hairline scratches",
        "factor": 0.88,
    },
    "Grade C (Fair / Average)": {
        "condition_desc": "Average - Fully functional, moderate scratches and minor body dent, battery < 80%",
        "defects": "Noticeable scratches, minor casing dent, degraded battery",
        "factor": 0.72,
    },
    "Grade D (Defective / Broken)": {
        "condition_desc": "Defective - Cracks on front display or non-functional camera/touch",
        "defects": "Cracked front glass / Touchscreen defect",
        "factor": 0.45,
    },
}

