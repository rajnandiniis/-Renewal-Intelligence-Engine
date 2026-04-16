"""
Configuration settings for the Renewal Intelligence Engine.
"""

import os
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Dict, List

load_dotenv()


@dataclass
class Config:
    """Application configuration."""

    # API Settings — uses Anthropic
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    # anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    # anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"))

    # Path Settings
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "./data"))
    output_dir: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "./output"))

    # Analysis Settings
    renewal_window_days: int = 90
    reference_date: str = "2026-04-15"

    # Risk Scoring Weights  (must sum to 1.0)
    weights: Dict[str, float] = field(default_factory=lambda: {
        "usage_decline":    0.25,
        "ticket_severity":  0.20,
        "sdk_deprecation":  0.15,
        "nps_signal":       0.10,
        "csm_sentiment":    0.20,
        "days_to_renewal":  0.10,
    })

    # SDK versions that are deprecated (security patches end 2026-04-30)
    deprecated_sdk_versions: List[str] = field(default_factory=lambda: [
        "v3.0.0", "v3.1.0", "v3.1.2", "v3.2.0", "v3.3.0", "v3.4.0", "v3.4.1",
    ])

    # SDK versions with known security vulnerability CVE-2026-1102 (fixed in v4.3.2)
    vulnerable_sdk_versions: List[str] = field(default_factory=lambda: [
        "v4.0.0", "v4.1.0", "v4.2.0", "v4.2.3",
    ])

    # Risk thresholds
    high_risk_threshold: float = 0.65
    medium_risk_threshold: float = 0.38

    # Regulated industries that amplify SDK/compliance risk
    regulated_industries: List[str] = field(default_factory=lambda: [
        "Financial Services", "Healthcare", "Government", "Insurance",
    ])

    def get_file_path(self, filename: str) -> str:
        return os.path.join(self.data_dir, filename)


config = Config()