"""
Grading and Pricing Intelligence Engine.
Simulates and models condition tiers and defect-based price deductions against
ground-truth verified baseline quotes.
All generated condition-graded records are explicitly labeled with
data_origin='sample_condition_graded' to ensure complete transparency.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List
from config import CONDITION_TIERS
from models import MobilePriceRecord

logger = logging.getLogger("grading_engine")


class GradingEngine:
    """Applies standard refurbished device grading factors to baseline prices."""

    def __init__(self, tiers: Dict = None):
        self.tiers = tiers or CONDITION_TIERS

    def generate_graded_records(
        self, baseline_record: MobilePriceRecord
    ) -> List[MobilePriceRecord]:
        """
        Takes a verified baseline (Grade A) record and generates the full condition
        matrix records (Grade B, Grade C, Grade D) with calibrated defect deductions.
        """
        graded_records: List[MobilePriceRecord] = []
        base_price = baseline_record.buyback_price

        for grade_name, grade_info in self.tiers.items():
            factor = grade_info["factor"]
            adjusted_price = int(round(base_price * factor))

            # Keep base record intact if it is Grade A
            if factor == 1.00:
                continue

            record = MobilePriceRecord(
                brand=baseline_record.brand,
                model=baseline_record.model,
                storage=baseline_record.storage,
                condition=f"{grade_name}: {grade_info['condition_desc']}",
                defects=grade_info["defects"],
                buyback_price=adjusted_price,
                source_url=baseline_record.source_url,
                timestamp=datetime.now(timezone.utc).isoformat(),
                data_origin="sample_condition_graded",
                currency=baseline_record.currency,
                confidence_score=0.85,
            )
            graded_records.append(record)

        return graded_records

    def build_full_dataset(
        self, verified_records: List[MobilePriceRecord], include_grading_matrix: bool = True
    ) -> List[MobilePriceRecord]:
        """
        Builds complete dataset containing verified scraped records and optionally
        appends condition-graded benchmark records.
        """
        all_records: List[MobilePriceRecord] = list(verified_records)

        if include_grading_matrix:
            for rec in verified_records:
                simulated = self.generate_graded_records(rec)
                all_records.extend(simulated)

        return all_records

