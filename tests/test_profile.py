"""Tests for the profile loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from myproject.profile import Profile, load_profile, slugify


@pytest.fixture()
def valid_profile_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid profile YAML and return its path."""
    data = {
        "first_name": "Test",
        "last_name": "User",
        "email": "test@microsoft.com",
        "phone": "+1555-000-0000",
        "address": "123 Main St",
        "city": "Redmond",
        "state": "Washington",
        "country": "United States",
        "postal_code": "98052",
        "resume_name": "resume.docx",
        "legally_authorized": "Yes",
        "needs_sponsorship": "No",
        "military_or_government": "No",
        "needs_visa_sponsorship": "No",
        "meets_degree_requirement": "Yes",
        "acknowledge_qualifications": True,
        "acknowledge_privacy_notice": True,
        "acknowledge_code_of_conduct": True,
        "target_titles": ["Cloud Solution Architect"],
        "search_location": "United States",
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def test_load_profile_returns_profile(valid_profile_yaml: Path) -> None:
    profile = load_profile(valid_profile_yaml)
    assert isinstance(profile, Profile)
    assert profile.first_name == "Test"
    assert profile.last_name == "User"
    assert profile.email == "test@microsoft.com"


def test_load_profile_target_titles(valid_profile_yaml: Path) -> None:
    profile = load_profile(valid_profile_yaml)
    assert profile.target_titles == ["Cloud Solution Architect"]
    assert profile.search_location == "United States"


def test_load_profile_defaults(tmp_path: Path) -> None:
    """Fields with defaults should populate even if missing from YAML."""
    data = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
        "phone": "555",
        "address": "1 St",
        "city": "X",
        "state": "Y",
        "country": "Z",
        "postal_code": "00000",
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    profile = load_profile(path)
    assert profile.legally_authorized == "Yes"
    assert profile.needs_sponsorship == "No"
    assert profile.acknowledge_qualifications is True


def test_load_profile_missing_file() -> None:
    with pytest.raises(FileNotFoundError, match="Profile not found"):
        load_profile(Path("/nonexistent/profile.yaml"))


def test_load_profile_missing_required_field(tmp_path: Path) -> None:
    data = {"first_name": "Test"}  # Missing most fields
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required profile fields"):
        load_profile(path)


def test_profile_is_frozen(valid_profile_yaml: Path) -> None:
    profile = load_profile(valid_profile_yaml)
    with pytest.raises(AttributeError):
        profile.first_name = "Changed"  # type: ignore[misc]


def test_load_profile_exclude_title_patterns(tmp_path: Path) -> None:
    """exclude_title_patterns loads from YAML and defaults to empty list."""
    data = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
        "phone": "555",
        "address": "1 St",
        "city": "X",
        "state": "Y",
        "country": "Z",
        "postal_code": "00000",
        "exclude_title_patterns": ["Principal", "Director"],
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    profile = load_profile(path)
    assert profile.exclude_title_patterns == ["Principal", "Director"]


def test_load_profile_exclude_title_patterns_defaults_empty(tmp_path: Path) -> None:
    data = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
        "phone": "555",
        "address": "1 St",
        "city": "X",
        "state": "Y",
        "country": "Z",
        "postal_code": "00000",
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    profile = load_profile(path)
    assert profile.exclude_title_patterns == []


def test_load_profile_exclude_title_patterns_invalid_type(tmp_path: Path) -> None:
    data = {
        "first_name": "Test",
        "last_name": "User",
        "email": "test@microsoft.com",
        "phone": "+1555-000-0000",
        "address": "123 Main St",
        "city": "Redmond",
        "state": "Washington",
        "country": "United States",
        "postal_code": "98052",
        "exclude_title_patterns": "not-a-list",
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="exclude_title_patterns must be a list"):
        load_profile(path)


# ---------------------------------------------------------------------------
# search_location
# ---------------------------------------------------------------------------


def test_load_profile_search_location(valid_profile_yaml: Path) -> None:
    profile = load_profile(valid_profile_yaml)
    assert profile.search_location == "United States"


def test_load_profile_search_location_defaults_empty(tmp_path: Path) -> None:
    data = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
        "phone": "555",
        "address": "1 St",
        "city": "X",
        "state": "Y",
        "country": "Z",
        "postal_code": "00000",
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    profile = load_profile(path)
    assert profile.search_location == ""


def test_load_profile_search_location_invalid_type(tmp_path: Path) -> None:
    data = {
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.com",
        "phone": "555",
        "address": "1 St",
        "city": "X",
        "state": "Y",
        "country": "Z",
        "postal_code": "00000",
        "search_location": ["not", "a", "string"],
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="search_location must be a string"):
        load_profile(path)


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("John Doe", "john-doe"),
        ("JOHN DOE", "john-doe"),
        ("john doe", "john-doe"),
        ("  John Doe  ", "john-doe"),
        ("John  Doe", "john-doe"),
        ("John O'Doe!", "john-odoe"),
        ("Mary-Jane Watson", "mary-jane-watson"),
        ("Agent 007", "agent-007"),
        ("John--Doe", "john-doe"),
        ("!!!", ""),
        ("", ""),
    ],
)
def test_slugify(input_text: str, expected: str) -> None:
    assert slugify(input_text) == expected
