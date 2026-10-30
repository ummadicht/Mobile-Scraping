"""
Flask Web Application — Refurbished Mobile Price Intelligence Dashboard.
Provides an interactive web interface for data analysts to:
  - Configure scraping parameters (condition multipliers, storage filters, timeouts, retries)
  - Trigger on-demand scraping for individual or all devices with custom parameters
  - Recalculate condition grading matrices dynamically
  - Filter, sort, search, and interactively simulate device valuations
"""
import copy
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

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
    CONDITION_TIERS,
    MAX_RETRIES,
    OUTPUT_CSV_PATH,
    OUTPUT_JSON_PATH,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_DEVICES,
)
from grading_engine import GradingEngine
from models import MobilePriceRecord
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
    """Load and deduplicate current pricing records from output.json if it exists."""
    if OUTPUT_JSON_PATH.exists():
        with open(OUTPUT_JSON_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        # Deduplicate by (source_url, storage, condition) keeping latest timestamp
        dedup: Dict[tuple, Dict[str, Any]] = {}
        for r in raw:
            grade_prefix = r.get("condition", "").split(":")[0].strip()
            key = (r.get("source_url", ""), r.get("storage", ""), grade_prefix)
            if key not in dedup or r.get("timestamp", "") >= dedup[key].get("timestamp", ""):
                dedup[key] = r
        return list(dedup.values())
    return []


def build_custom_tiers(params: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build condition tiers dictionary using user-supplied multiplier percentages."""
    tiers = copy.deepcopy(CONDITION_TIERS)
    try:
        if "grade_b" in params and params["grade_b"] is not None:
            tiers["Grade B (Good)"]["factor"] = round(float(params["grade_b"]) / 100.0, 4)
        if "grade_c" in params and params["grade_c"] is not None:
            tiers["Grade C (Fair / Average)"]["factor"] = round(float(params["grade_c"]) / 100.0, 4)
        if "grade_d" in params and params["grade_d"] is not None:
            tiers["Grade D (Defective / Broken)"]["factor"] = round(float(params["grade_d"]) / 100.0, 4)
    except (ValueError, TypeError) as exc:
        logger.warning("Invalid custom tier multiplier supplied, using defaults: %s", exc)
    return tiers


def filter_by_storage(
    records: List[MobilePriceRecord], allowed_storages: List[str]
) -> List[MobilePriceRecord]:
    """Filter extracted records by user-selected storage capacities."""
    if not allowed_storages:
        return records
    normalized_allowed = {s.upper().replace(" ", "") for s in allowed_storages}
    filtered = [
        r for r in records
        if r.storage.upper().replace(" ", "") in normalized_allowed
    ]
    return filtered


def compute_storage_insights(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute per-model storage variant data for the UI charts."""
    verified = [r for r in records if r.get("data_origin") == "verified_scraped"]

    groups: Dict[str, Dict[str, Dict]] = {}
    for r in verified:
        model_name = r.get("model", "")
        base = model_name.split("(")[0].strip() if "(" in model_name else model_name
        storage = r.get("storage", "Standard")
        groups.setdefault(base, {})[storage] = r

    result = []
    for base_model, storage_map in groups.items():
        variants = list(storage_map.values())
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
    """Build condition degradation rows for the case study panel."""
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
    seen_grades = set()
    for r in sorted(target, key=lambda x: x.get("buyback_price", 0), reverse=True):
        cond = r.get("condition", "")
        grade_letter = (
            "A" if "Grade A" in cond
            else "B" if "Grade B" in cond
            else "C" if "Grade C" in cond
            else "D"
        )
        if grade_letter in seen_grades:
            continue
        seen_grades.add(grade_letter)
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


def upsert_records(
    existing: List[Dict[str, Any]],
    new_records: List[MobilePriceRecord],
    include_matrix: bool = True,
    target_urls: set = None,
) -> tuple:
    """Upsert scraped and graded records cleanly without duplicates."""
    if not include_matrix and target_urls:
        # Remove simulated records for the scraped URLs if user opted for live-only
        existing = [
            r for r in existing
            if not (r.get("source_url") in target_urls and r.get("data_origin") == "sample_condition_graded")
        ]

    existing_map = {
        (r.get("source_url", ""), r.get("storage", ""), r.get("condition", "").split(":")[0].strip()): idx
        for idx, r in enumerate(existing)
    }

    updated_count = 0
    added_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for rec in new_records:
        rec_dict = rec.model_dump()
        rec_dict["timestamp"] = now_iso
        grade_prefix = rec.condition.split(":")[0].strip()
        key = (rec.source_url, rec.storage, grade_prefix)
        if key in existing_map:
            idx = existing_map[key]
            existing[idx].update(rec_dict)
            updated_count += 1
        else:
            existing.append(rec_dict)
            existing_map[key] = len(existing) - 1
            added_count += 1

    return existing, updated_count, added_count


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Serve the main analytics dashboard."""
    records = load_records()
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
    Trigger a scrape for one or more selected URLs with custom scrape parameters.
    Expects JSON body:
    {
      "url": "https://www.cashify.in/...", (or "urls": [...])
      "include_matrix": true,
      "storages": ["64 GB", "128 GB", "256 GB", "512 GB", "1 TB"],
      "grade_b": 88,
      "grade_c": 72,
      "grade_d": 45,
      "timeout": 15,
      "retries": 3
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    urls = data.get("urls") or ([data["url"]] if data.get("url") else [])
    urls = [u.strip() for u in urls if u and u.strip()]

    if not urls:
        return jsonify({"success": False, "error": "No URL provided."}), 400

    for u in urls:
        if not re.match(r"https://www\.cashify\.in/sell-old-mobile-phone/", u):
            return jsonify({
                "success": False,
                "error": f"Unsupported URL: {u}. Only Cashify /sell-old-mobile-phone/ URLs are allowed."
            }), 400

    include_matrix = bool(data.get("include_matrix", True))
    allowed_storages = data.get("storages") or []
    timeout = max(5, min(60, int(data.get("timeout", REQUEST_TIMEOUT_SECONDS))))
    retries = max(1, min(5, int(data.get("retries", MAX_RETRIES))))
    custom_tiers = build_custom_tiers(data)

    try:
        scraper = CashifyScraper(timeout=timeout, max_retries=retries)
        engine = GradingEngine(tiers=custom_tiers)

        all_verified: List[MobilePriceRecord] = []
        for u in urls:
            extracted = scraper.scrape_url(u)
            if allowed_storages:
                extracted = filter_by_storage(extracted, allowed_storages)
            all_verified.extend(extracted)

        if not all_verified:
            return jsonify({
                "success": False,
                "error": "No matching pricing records found for the selected URL(s) and storage filters."
            }), 404

        new_all = engine.build_full_dataset(all_verified, include_grading_matrix=include_matrix)
        existing = load_records()
        scraped_urls = {r.source_url for r in all_verified}

        existing, updated_count, added_count = upsert_records(
            existing, new_all, include_matrix=include_matrix, target_urls=scraped_urls
        )

        save_to_json(existing, OUTPUT_JSON_PATH)
        save_to_csv_raw(existing, OUTPUT_CSV_PATH)

        model_name = all_verified[0].model.split("(")[0].strip() if len(urls) == 1 else f"{len(urls)} device families"
        msg = (
            f"Scraped {model_name} ({len(all_verified)} verified variants)! "
            f"Updated {updated_count} records, added {added_count} new records."
        )

        return jsonify({
            "success": True,
            "message": msg,
            "new_records": [r.model_dump() for r in all_verified],
            "total_records": len(existing),
            "updated_count": updated_count,
            "added_count": added_count,
        })

    except Exception as exc:
        logger.exception("Error during custom scrape")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/scrape-all", methods=["POST"])
def api_scrape_all():
    """Trigger a full catalog scrape across all target devices using custom parameters."""
    data = request.get_json(force=True, silent=True) or {}
    include_matrix = bool(data.get("include_matrix", True))
    allowed_storages = data.get("storages") or []
    timeout = max(5, min(60, int(data.get("timeout", REQUEST_TIMEOUT_SECONDS))))
    retries = max(1, min(5, int(data.get("retries", MAX_RETRIES))))
    custom_tiers = build_custom_tiers(data)

    try:
        scraper = CashifyScraper(timeout=timeout, max_retries=retries)
        engine = GradingEngine(tiers=custom_tiers)

        all_verified: List[MobilePriceRecord] = []
        errors = []
        for target in TARGET_DEVICES:
            try:
                extracted = scraper.scrape_url(target["url"])
                if allowed_storages:
                    extracted = filter_by_storage(extracted, allowed_storages)
                all_verified.extend(extracted)
            except Exception as e:
                errors.append(f"{target['brand']} {target['model_family']}: {e}")

        if not all_verified:
            return jsonify({
                "success": False,
                "error": "No records scraped matching your filters. " + "; ".join(errors)
            }), 500

        final_records = engine.build_full_dataset(all_verified, include_grading_matrix=include_matrix)
        existing = load_records()
        scraped_urls = {r.source_url for r in all_verified}

        existing, updated_count, added_count = upsert_records(
            existing, final_records, include_matrix=include_matrix, target_urls=scraped_urls
        )

        save_to_json(existing, OUTPUT_JSON_PATH)
        save_to_csv_raw(existing, OUTPUT_CSV_PATH)

        return jsonify({
            "success": True,
            "message": f"Full catalog refreshed! {updated_count} updated, {added_count} added.",
            "verified_count": len(all_verified),
            "total_records": len(existing),
            "updated_count": updated_count,
            "added_count": added_count,
            "errors": errors,
        })

    except Exception as exc:
        logger.exception("Error during full scrape")
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/recalculate-grades", methods=["POST"])
def api_recalculate_grades():
    """
    Recalculate simulated condition grades on existing verified records without network scraping.
    """
    data = request.get_json(force=True, silent=True) or {}
    include_matrix = bool(data.get("include_matrix", True))
    custom_tiers = build_custom_tiers(data)

    records = load_records()
    verified_dicts = [r for r in records if r.get("data_origin") == "verified_scraped"]
    if not verified_dicts:
        return jsonify({"success": False, "error": "No verified records available to recalculate."}), 400

    verified_objs = [MobilePriceRecord(**r) for r in verified_dicts]
    engine = GradingEngine(tiers=custom_tiers)
    recalculated = engine.build_full_dataset(verified_objs, include_grading_matrix=include_matrix)

    out_dicts = [r.model_dump() for r in recalculated]
    save_to_json(out_dicts, OUTPUT_JSON_PATH)
    save_to_csv_raw(out_dicts, OUTPUT_CSV_PATH)

    return jsonify({
        "success": True,
        "message": f"Recalculated dataset using Grade B={data.get('grade_b', 88)}%, C={data.get('grade_c', 72)}%, D={data.get('grade_d', 45)}% ({len(out_dicts)} total records).",
        "total_records": len(out_dicts),
    })


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
# Internal helpers
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
    fieldnames = [
        "brand", "model", "storage", "ram", "cores", "camera", "condition", "defects",
        "buyback_price", "currency", "data_origin", "confidence_score",
        "source_url", "timestamp",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in fieldnames})
    logger.info("Exported %d records to %s", len(records), path)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
