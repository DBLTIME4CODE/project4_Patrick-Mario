"""Profile loader — reads user configuration from profile.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug (lowercase, alphanumeric and hyphens only)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


@dataclass(frozen=True)
class Profile:
    """All data needed to fill out a CareerHub application."""

    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    address_line_2: str
    city: str
    state: str
    country: str
    postal_code: str
    resume_name: str

    # Work authorization
    legally_authorized: str  # "Yes" / "No"
    needs_sponsorship: str  # "Yes" / "No"

    # Candidate questions
    military_or_government: str  # "Yes" / "No"

    # Job-specific questions (radio buttons)
    needs_visa_sponsorship: str  # "Yes" / "No"
    meets_degree_requirement: str  # "Yes" / "No"

    # Acknowledgments
    acknowledge_qualifications: bool
    acknowledge_privacy_notice: bool
    acknowledge_code_of_conduct: bool

    # Job search
    target_titles: list[str] = field(default_factory=list)
    search_location: str = ""
    exclude_title_patterns: list[str] = field(default_factory=list)


def load_profile(path: Path | str = "profile.yaml") -> Profile:
    """Load and validate a profile from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Profile not found at {config_path}. "
            "Copy profile.yaml.example and fill in your details."
        )

    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    required_fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "city",
        "state",
        "country",
        "postal_code",
    ]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        raise ValueError(f"Missing required profile fields: {', '.join(missing)}")

    raw_patterns = data.get("exclude_title_patterns", [])
    if not isinstance(raw_patterns, list) or not all(isinstance(p, str) for p in raw_patterns):
        raise ValueError("exclude_title_patterns must be a list of strings")

    search_location = data.get("search_location", "")
    if not isinstance(search_location, str):
        raise ValueError("search_location must be a string")

    return Profile(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        phone=data["phone"],
        address=data["address"],
        address_line_2=data.get("address_line_2", ""),
        city=data["city"],
        state=data["state"],
        country=data["country"],
        postal_code=data["postal_code"],
        resume_name=data.get("resume_name", ""),
        legally_authorized=data.get("legally_authorized", "Yes"),
        needs_sponsorship=data.get("needs_sponsorship", "No"),
        military_or_government=data.get("military_or_government", "No"),
        needs_visa_sponsorship=data.get("needs_visa_sponsorship", "No"),
        meets_degree_requirement=data.get("meets_degree_requirement", "Yes"),
        acknowledge_qualifications=data.get("acknowledge_qualifications", True),
        acknowledge_privacy_notice=data.get("acknowledge_privacy_notice", True),
        acknowledge_code_of_conduct=data.get("acknowledge_code_of_conduct", True),
        target_titles=data.get("target_titles", []),
        search_location=search_location,
        exclude_title_patterns=raw_patterns,
    )
