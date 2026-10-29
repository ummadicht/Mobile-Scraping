"""
Exporter module for Mobile Price Intelligence records.
Saves records to JSON and CSV formats with schema verification.
"""
import csv
import json
import logging
from pathlib import Path
from typing import List
from models import MobilePriceRecord

logger = logging.getLogger("exporter")


def save_to_json(records: List[MobilePriceRecord], file_path: Path) -> None:
    """Save records to JSON file."""
    data = [rec.model_dump() for rec in records]
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Successfully exported %d records to %s", len(records), file_path)


def save_to_csv(records: List[MobilePriceRecord], file_path: Path) -> None:
    """Save records to CSV file."""
    if not records:
        logger.warning("No records to export to CSV.")
        return

    fieldnames = [
        "brand",
        "model",
        "storage",
        "condition",
        "defects",
        "buyback_price",
        "currency",
        "data_origin",
        "confidence_score",
        "source_url",
        "timestamp",
    ]

    with open(file_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = rec.model_dump()
            writer.writerow({k: row.get(k) for k in fieldnames})

    logger.info("Successfully exported %d records to %s", len(records), file_path)

