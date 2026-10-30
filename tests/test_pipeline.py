"""
Unit tests for Mobile Price Intelligence System.
Tests model validation, scraping extraction, grading logic, and file export.
"""
import json
import csv
from pathlib import Path
import pytest
from pydantic import ValidationError

from models import MobilePriceRecord
from scraper import CashifyScraper
from grading_engine import GradingEngine
from exporter import save_to_csv, save_to_json


def test_mobile_price_record_valid():
    """Verify that a valid record instantiates without error."""
    rec = MobilePriceRecord(
        brand="Apple",
        model="Apple iPhone 13 (4 GB/128 GB)",
        storage="128 GB",
        condition="Grade A: Like New",
        defects="None",
        buyback_price=53150,
        source_url="https://www.cashify.in/test",
        data_origin="verified_scraped",
    )
    assert rec.brand == "Apple"
    assert rec.buyback_price == 53150
    assert rec.currency == "INR"
    assert rec.confidence_score == 1.0


def test_mobile_price_record_invalid_price():
    """Verify that negative prices trigger a ValidationError."""
    with pytest.raises(ValidationError):
        MobilePriceRecord(
            brand="Samsung",
            model="Galaxy S21",
            storage="128 GB",
            condition="Good",
            defects="None",
            buyback_price=-500,
            source_url="https://www.cashify.in/test",
            data_origin="verified_scraped",
        )


def test_scraper_extract_from_mock_html():
    """Test extracting variant record from synthetic HTML with Schema.org itemprop and specifications."""
    scraper = CashifyScraper()
    mock_payload = (
        '<html><body>'
        '<div itemprop="brand">Samsung</div>'
        '<img itemprop="image" alt="Samsung Galaxy S21 5G (8 GB/256 GB)" />'
        '<div itemprop="offers"><span itemprop="price">13280</span><span itemprop="priceCurrency">INR</span></div>'
        'self.__next_f.push([1,"\\"specifications\\":{\\"storage\\":[{\\"id\\":1338,\\"dval\\":\\"256 GB\\"}],\\"ram\\":[{\\"id\\":832,\\"dval\\":\\"8 GB RAM\\"}],\\"cores\\":[{\\"id\\":839,\\"dval\\":\\"8\\"}],\\"backCamera\\":[{\\"id\\":1267,\\"dval\\":\\"12 MP\\"},{\\"id\\":1899,\\"dval\\":\\"64 MP\\"}]}"]);'
        '</body></html>'
    )
    rec = scraper.scrape_single_variant_page(mock_payload, "https://www.cashify.in/sell-old-mobile-phone/used-samsung-galaxy-s21-5g-8-gb-256-gb")
    assert rec is not None
    assert rec.brand == "Samsung"
    assert rec.storage == "256 GB"
    assert rec.ram == "8 GB RAM"
    assert rec.cores == "8"
    assert rec.buyback_price == 13280
    assert rec.data_origin == "verified_scraped"


def test_grading_engine_multipliers():
    """Verify that the grading engine applies expected factors and labels origin."""
    engine = GradingEngine()
    base_rec = MobilePriceRecord(
        brand="Apple",
        model="Apple iPhone 13 (4 GB/128 GB)",
        storage="128 GB",
        condition="Grade A: Like New / Flawless",
        defects="None",
        buyback_price=10000,
        source_url="https://www.cashify.in/test",
        data_origin="verified_scraped",
    )
    simulated = engine.generate_graded_records(base_rec)
    assert len(simulated) == 3  # Grade B, Grade C, Grade D

    # Grade B (0.88 factor)
    assert simulated[0].buyback_price == 8800
    assert simulated[0].data_origin == "sample_condition_graded"
    assert "Grade B" in simulated[0].condition

    # Grade C (0.72 factor)
    assert simulated[1].buyback_price == 7200
    assert "Grade C" in simulated[1].condition

    # Grade D (0.45 factor)
    assert simulated[2].buyback_price == 4500
    assert "Grade D" in simulated[2].condition
    assert "Cracked" in simulated[2].defects


def test_export_json_and_csv(tmp_path: Path):
    """Verify export to JSON and CSV formats."""
    json_path = tmp_path / "test_output.json"
    csv_path = tmp_path / "test_output.csv"

    test_records = [
        MobilePriceRecord(
            brand="Samsung",
            model="Galaxy S21 5G (8 GB/128 GB)",
            storage="128 GB",
            condition="Grade A: Like New",
            defects="None",
            buyback_price=34930,
            source_url="https://www.cashify.in/samsung-s21",
            data_origin="verified_scraped",
        )
    ]

    save_to_json(test_records, json_path)
    assert json_path.exists()
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["buyback_price"] == 34930

    save_to_csv(test_records, csv_path)
    assert csv_path.exists()
    with open(csv_path, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 1
    assert reader[0]["model"] == "Galaxy S21 5G (8 GB/128 GB)"
    assert int(reader[0]["buyback_price"]) == 34930

