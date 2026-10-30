"""
Data models and schema validation for mobile price intelligence records.
Includes device technical specifications (RAM, CPU Cores, Cameras) and commercial parameters.
"""
from datetime import datetime, timezone
from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MobilePriceRecord(BaseModel):
    """Represents a validated mobile pricing record with specifications and parameters."""
    model_config = ConfigDict(frozen=True)

    brand: str = Field(..., description="Device manufacturer, e.g., Apple, Samsung")
    model: str = Field(..., description="Device model with specifications, e.g., Samsung Galaxy S21 5G (8 GB/256 GB)")
    storage: str = Field(..., description="Storage variant, e.g., 64 GB, 128 GB, 256 GB")
    ram: Optional[str] = Field(default=None, description="Device RAM, e.g., 4 GB, 8 GB RAM")
    cores: Optional[str] = Field(default=None, description="Processor core count, e.g., 8, 6")
    camera: Optional[str] = Field(default=None, description="Camera setup, e.g., 12 MP, 64 MP")
    condition: str = Field(..., description="Device condition description or grade")
    defects: str = Field(..., description="Defects or hardware faults present on device")
    buyback_price: int = Field(..., ge=0, description="Actual buyback price in local currency integer value")
    source_url: str = Field(..., description="Source URL where the price quote originated")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of record creation or collection"
    )
    data_origin: Literal["verified_scraped", "sample_condition_graded"] = Field(
        ...,
        description="Origin flag: 'verified_scraped' for live extracted quotes, 'sample_condition_graded' for calibrated matrix"
    )
    currency: str = Field(default="INR", description="Currency ISO code")
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence: 1.0 for verified DOM/RSC scrape, 0.85 for simulated condition"
    )

    @field_validator("buyback_price")
    @classmethod
    def validate_positive_price(cls, v: int) -> int:
        if v < 0:
            raise ValueError("buyback_price must be non-negative")
        return v

    @field_validator("brand")
    @classmethod
    def clean_brand(cls, v: str) -> str:
        return v.strip().title()
