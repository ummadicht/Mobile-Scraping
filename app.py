"""
Flask Web Application — Refurbished Mobile Price Intelligence Dashboard.
Provides a professional web interface for data analysts to:
  - View all tracked device buyback prices
  - Trigger on-demand scraping for individual or all devices
  - Filter, search, and analyze pricing data
  - Download CSV and JSON exports
"""
import json
import logging
import os
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
)

# Ensure the project root is in Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    BASE_DIR,
    OUTPUT_CSV_PATH,
    OUTPUT_JSON_PATH,
    TARGET_DEVICES,
)
from exporter import save_to_csv, save_to_json
from grading_engine import GradingEngine
from scraper import CashifyScraper

# ---------------------------------------------------------------------------
# App Initialization
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", "mobile-price-intelligence-poc")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("webapp")


# ---------------------------------------------------------------------------
# Helper Utilities
# ---------------------------------------------------------------------------
def load_records() -> List[Dict[str, Any]]:
    """Load current pricing records from output.json if it exists."""
    if OUTPUT_JSON_PATH.exists():
        with open(OUTPUT_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def compute_storage_insights(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Compute per-model storage variant data for the bar chart in the UI.
    Returns a list of model groups with sorted variants and percentages.
    """
    verified = [r for r in records if r.get("data_origin") == "verified_scraped"]

    # Group by base model name (without storage spec)
    groups: Dict[str, List[Dict]] = {}
    for r in verified:
        model_name = r.get("model", "")
        base = model_name.split("(")[0].strip() if "(" in model_name else model_name
        groups.setdefault(base, []).append(r)

    result = []
    for base_model, variants in groups.items():
        if len(variants) < 2:
            continue
        sorted_variants = sorted(variants, key=lambda x: x.get("buyback_price", 0))
        max_price = sorted_variants[-1]["buyback_price"] if sorted_variants else 1
        enriched = []
        for v in sorted_variants:
            pct = int((v["buyback_price"] / max_price) * 100) if max_price else 0
            enriched.append({
                "storage": v.get("storage", ""),
                "buyback_price": v.get("buyback_price", 0),
                "pct": pct,
            })
        result.append({"model": base_model, "variants": enriched})

    return result


def compute_condition_insights(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build condition degradation rows for the iPhone 13 128GB case study panel.
    """
    target = [
        r for r in records
        if "iPhone 13" in r.get("model", "") and r.get("storage", "") == "128 GB"
    ]
    if not target:
        return []
    max_price = max(r["buyback_price"] for r in target)
    rows = []
    grade_map = {"A": "grade-a", "B": "grade-b", "C": "grade-c", "D": "grade-d"}
    grade_bar_map = {
        "A": "bg-gradient-to-r from-green-400 to-green-500",
        "B": "bg-gradient-to-r from-blue-400 to-blue-500",
        "C": "bg-gradient-to-r from-yellow-400 to-yellow-500",
        "D": "bg-gradient-to-r from-red-400 to-red-500",
    }
    for r in sorted(target, key=lambda x: x.get("buyback_price", 0), reverse=True):
        cond = r.get("condition", "")
        grade_letter = (
            "A" if "Grade A" in cond
            else "B" if "Grade B" in cond
            else "C" if "Grade C" in cond
            else "D"
        )
        pct = int((r["buyback_price"] / max_price) * 100) if max_price else 0
        rows.append({
            "grade_letter": grade_letter,
            "badge_class": grade_map.get(grade_letter, "grade-d"),
            "bar_class": grade_bar_map.get(grade_letter, ""),
            "buyback_price": r["buyback_price"],
            "pct": pct,
        })
    return rows


def compute_kpis(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute key performance indicators for the dashboard header."""
    if not records:
        return {
            "total_records": 0,
            "verified_count": 0,
            "simulated_count": 0,
            "avg_price": 0,
            "max_price": 0,
            "max_device": "N/A",
            "min_price": 0,
            "min_device": "N/A",
            "brands_tracked": 0,
            "last_updated": "Never",
        }

    verified = [r for r in records if r.get("data_origin") == "verified_scraped"]
    prices = [r["buyback_price"] for r in verified if r.get("buyback_price", 0) > 0]
    max_rec = max(verified, key=lambda x: x.get("buyback_price", 0)) if verified else None
    min_rec = min(verified, key=lambda x: x.get("buyback_price", 0)) if verified else None
    brands = set(r.get("brand", "") for r in verified)

    # Get last updated timestamp from records
    timestamps = [r.get("timestamp", "") for r in records if r.get("timestamp")]
    last_updated = "Never"
    if timestamps:
        ts_sorted = sorted(timestamps, reverse=True)
        try:
            dt = datetime.fromisoformat(ts_sorted[0])
            last_updated = dt.strftime("%d %b %Y, %I:%M %p UTC")
        except Exception:
            last_updated = ts_sorted[0][:19].replace("T", " ")

    return {
        "total_records": len(records),
        "verified_count": len(verified),
        "simulated_count": len(records) - len(verified),
        "avg_price": int(sum(prices) / len(prices)) if prices else 0,
        "max_price": max(prices) if prices else 0,
        "max_device": max_rec["model"] if max_rec else "N/A",
        "min_price": min(prices) if prices else 0,
        "min_device": min_rec["model"] if min_rec else "N/A",
        "brands_tracked": len(brands),
        "last_updated": last_updated,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Serve the main analytics dashboard."""
    records = load_records()
    # Sort with newest timestamps at the top
    records = sorted(records, key=lambda x: x.get("timestamp", ""), reverse=True)
    kpis = compute_kpis(records)
    storage_insights = compute_storage_insights(records)
    condition_insights = compute_condition_insights(records)
    return render_template(
        "index.html",
        records=records,
        kpis=kpis,
        storage_insights=storage_insights,
        condition_insights=condition_insights,
        target_devices=TARGET_DEVICES,
    )


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """
    Trigger a scrape for a single device.
    Expects JSON body: { "url": "https://cashify.in/..." }
    """
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"success": False, "error": "No URL provided."}), 400

    # Validate it's a Cashify mobile pricing URL
    if not re.match(r"https://www\.cashify\.in/sell-old-mobile-phone/", url):
        return jsonify({
            "success": False,
            "error": "Only Cashify /sell-old-mobile-phone/ URLs are supported."
        }), 400

    try:
        scraper = CashifyScraper()
        engine = GradingEngine()

        new_verified = scraper.scrape_url(url)
        if not new_verified:
            return jsonify({
                "success": False,
                "error": f"No pricing data found for that URL. The device may not be listed on Cashify."
            }), 404

        new_all = engine.build_full_dataset(new_verified, include_grading_matrix=True)

        # Upsert into existing records: update existing by key, or append if new
        existing = load_records()
        existing_map = {
            (r.get("source_url", ""), r.get("storage", ""), r.get("data_origin", "")): idx
            for idx, r in enumerate(existing)
        }

        updated_count = 0
        added_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for rec in new_all:
            rec_dict = rec.model_dump()
            rec_dict["timestamp"] = now_iso
            key = (rec.source_url, rec.storage, rec.data_origin)
            if key in existing_map:
                idx = existing_map[key]
                existing[idx].update(rec_dict)
                updated_count += 1
            else:
                existing.append(rec_dict)
                existing_map[key] = len(existing) - 1
                added_count += 1

        # Persist updated dataset
        save_to_json(existing, OUTPUT_JSON_PATH)
        save_to_csv_raw(existing, OUTPUT_CSV_PATH)

        model_name = new_verified[0].model.split("(")[0].strip() if new_verified else "Device"
        msg = f"Successfully scraped {model_name}! Updated {updated_count} records with fresh prices and timestamps, added {added_count} new records."

        return jsonify({
            "success": True,
            "message": msg,
            "new_records": [r.model_dump() for r in new_verified],
            "total_records": len(existing),
            "updated_count": updated_count,
            "added_count": added_count,
        })

    except Exception as exc:
        logger.exception("Error during single scrape")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/scrape-all", methods=["POST"])
def api_scrape_all():
    """Trigger a full catalog scrape across all configured target devices."""
    try:
        scraper = CashifyScraper()
        engine = GradingEngine()

        all_verified = []
        errors = []
        for target in TARGET_DEVICES:
            try:
                extracted = scraper.scrape_url(target["url"])
                all_verified.extend(extracted)
            except Exception as e:
                errors.append(f"{target['brand']} {target['model_family']}: {e}")

        if not all_verified:
            return jsonify({
                "success": False,
                "error": "No records scraped from any target. " + "; ".join(errors)
            }), 500

        final_records = engine.build_full_dataset(all_verified, include_grading_matrix=True)

        existing = load_records()
        existing_map = {
            (r.get("source_url", ""), r.get("storage", ""), r.get("data_origin", "")): idx
            for idx, r in enumerate(existing)
        }

        updated_count = 0
        added_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for rec in final_records:
            rec_dict = rec.model_dump()
            rec_dict["timestamp"] = now_iso
            key = (rec.source_url, rec.storage, rec.data_origin)
            if key in existing_map:
                idx = existing_map[key]
                existing[idx].update(rec_dict)
                updated_count += 1
            else:
                existing.append(rec_dict)
                existing_map[key] = len(existing) - 1
                added_count += 1

        save_to_json(existing, OUTPUT_JSON_PATH)
        save_to_csv_raw(existing, OUTPUT_CSV_PATH)

        return jsonify({
            "success": True,
            "message": f"Full catalog refreshed! {updated_count} records updated with current prices, {added_count} new added.",
            "verified_count": len(all_verified),
            "total_records": len(existing),
            "updated_count": updated_count,
            "added_count": added_count,
            "errors": errors,
        })

    except Exception as exc:
        logger.exception("Error during full scrape")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/records")
def api_records():
    """Return current pricing records as JSON API response."""
    records = load_records()
    kpis = compute_kpis(records)
    return jsonify({"records": records, "kpis": kpis})


@app.route("/download/csv")
def download_csv():
    """Serve latest output.csv as a file download."""
    if not OUTPUT_CSV_PATH.exists():
        return "No CSV export available. Run a scrape first.", 404
    return send_file(
        OUTPUT_CSV_PATH,
        as_attachment=True,
        download_name=f"mobile_buyback_prices_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mimetype="text/csv",
    )


@app.route("/download/json")
def download_json():
    """Serve latest output.json as a file download."""
    if not OUTPUT_JSON_PATH.exists():
        return "No JSON export available. Run a scrape first.", 404
    return send_file(
        OUTPUT_JSON_PATH,
        as_attachment=True,
        download_name=f"mobile_buyback_prices_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# Internal helpers (bypassing Pydantic model layer for raw dict I/O)
# ---------------------------------------------------------------------------
def save_to_json(records, path: Path):
    """Serialize records (Pydantic or dicts) to JSON."""
    data = []
    for r in records:
        if hasattr(r, "model_dump"):
            data.append(r.model_dump())
        elif isinstance(r, dict):
            data.append(r)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Exported %d records to %s", len(data), path)


def save_to_csv_raw(records: List[Dict[str, Any]], path: Path):
    """Write raw dicts to CSV."""
    import csv
    fieldnames = [
        "brand", "model", "storage", "condition", "defects",
        "buyback_price", "currency", "data_origin", "confidence_score",
        "source_url", "timestamp",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in fieldnames})
    logger.info("Exported %d records to %s", len(records), path)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
