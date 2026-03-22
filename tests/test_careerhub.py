"""Tests for CareerHub automation helpers (non-browser tests)."""

from __future__ import annotations

from myproject.careerhub import (
    CareerHubError,
    JobListing,
    NoResultsError,
    ScrapeError,
    _build_search_queries,
    _build_search_url,
    _deduplicate_jobs,
    _extract_job_id,
    _normalize_job_url,
    _sanitize_for_selector,
    filter_jobs,
    sanitize_debug_html,
)
from myproject.profile import Profile


def _make_profile(**overrides: object) -> Profile:
    """Create a Profile with sensible defaults, overriding specific fields."""
    defaults = dict(
        first_name="Test",
        last_name="User",
        email="t@m.com",
        phone="555",
        address="1 St",
        address_line_2="",
        city="X",
        state="Y",
        country="Z",
        postal_code="00000",
        resume_name="resume.docx",
        legally_authorized="Yes",
        needs_sponsorship="No",
        military_or_government="No",
        needs_visa_sponsorship="No",
        meets_degree_requirement="Yes",
        acknowledge_qualifications=True,
        acknowledge_privacy_notice=True,
        acknowledge_code_of_conduct=True,
        target_titles=["Cloud Solution"],
        search_location="United States",
        exclude_title_patterns=[],
    )
    defaults.update(overrides)
    return Profile(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _build_search_queries
# ---------------------------------------------------------------------------


def test_build_search_queries_returns_target_titles() -> None:
    profile = _make_profile(
        target_titles=["Cloud Solution", "Solution Engineer"],
    )
    queries = _build_search_queries(profile)
    assert queries == ["Cloud Solution", "Solution Engineer"]


def test_build_search_queries_no_titles() -> None:
    profile = _make_profile(target_titles=[])
    queries = _build_search_queries(profile)
    assert queries == []


def test_build_search_queries_single_title() -> None:
    profile = _make_profile(target_titles=["Architect"])
    queries = _build_search_queries(profile)
    assert queries == ["Architect"]


# ---------------------------------------------------------------------------
# JobListing
# ---------------------------------------------------------------------------


def test_job_listing_defaults() -> None:
    job = JobListing(title="Test Job", url="https://example.com/jobs/123")
    assert job.title == "Test Job"
    assert job.url == "https://example.com/jobs/123"
    assert job.location == ""
    assert job.job_id == ""


# ---------------------------------------------------------------------------
# _normalize_job_url
# ---------------------------------------------------------------------------


def test_normalize_job_url_relative() -> None:
    assert _normalize_job_url("/careerhub/explore/jobs/123") == (
        "https://careerhub.microsoft.com/careerhub/explore/jobs/123"
    )


def test_normalize_job_url_absolute() -> None:
    url = "https://careerhub.microsoft.com/careerhub/explore/jobs/456"
    assert _normalize_job_url(url) == url


# ---------------------------------------------------------------------------
# _extract_job_id
# ---------------------------------------------------------------------------


def test_extract_job_id_basic() -> None:
    url = "https://careerhub.microsoft.com/careerhub/explore/jobs/12345"
    assert _extract_job_id(url) == "12345"


def test_extract_job_id_trailing_slash() -> None:
    url = "https://careerhub.microsoft.com/careerhub/explore/jobs/12345/"
    assert _extract_job_id(url) == "12345"


# ---------------------------------------------------------------------------
# _deduplicate_jobs
# ---------------------------------------------------------------------------


def test_deduplicate_jobs_removes_dupes() -> None:
    jobs = [
        JobListing(title="A", url="https://x.com/1"),
        JobListing(title="B", url="https://x.com/2"),
        JobListing(title="A copy", url="https://x.com/1"),
    ]
    result = _deduplicate_jobs(jobs)
    assert len(result) == 2
    assert result[0].title == "A"
    assert result[1].title == "B"


def test_deduplicate_jobs_preserves_order() -> None:
    jobs = [
        JobListing(title="C", url="https://x.com/3"),
        JobListing(title="A", url="https://x.com/1"),
    ]
    assert _deduplicate_jobs(jobs) == jobs


def test_deduplicate_jobs_empty() -> None:
    assert _deduplicate_jobs([]) == []


# ---------------------------------------------------------------------------
# _build_search_url
# ---------------------------------------------------------------------------


def test_build_search_url_encodes_spaces() -> None:
    url = _build_search_url("Cloud Architect")
    assert "q=Cloud+Architect" in url


def test_build_search_url_encodes_special_chars() -> None:
    url = _build_search_url("C++ Engineer")
    assert "q=C%2B%2B+Engineer" in url


# ---------------------------------------------------------------------------
# _sanitize_for_selector
# ---------------------------------------------------------------------------


def test_sanitize_strips_quotes() -> None:
    assert _sanitize_for_selector("value\"with'quotes") == "valuewithquotes"


def test_sanitize_strips_backslash() -> None:
    assert _sanitize_for_selector("back\\slash") == "backslash"


def test_sanitize_strips_newlines() -> None:
    assert _sanitize_for_selector("line\none\rtwo") == "line one two"


def test_sanitize_preserves_normal_text() -> None:
    assert _sanitize_for_selector("Normal Value 123") == "Normal Value 123"


# ---------------------------------------------------------------------------
# sanitize_debug_html
# ---------------------------------------------------------------------------


def test_sanitize_debug_html_strips_scripts() -> None:
    html = '<div>Hello</div><script>var token="secret";</script><p>World</p>'
    result = sanitize_debug_html(html)
    assert "<script" not in result
    assert "secret" not in result
    assert "<div>Hello</div>" in result
    assert "<p>World</p>" in result


def test_sanitize_debug_html_strips_data_attrs() -> None:
    html = '<div data-token="abc123" data-session-id="xyz" class="keep">Text</div>'
    result = sanitize_debug_html(html)
    assert "data-token" not in result
    assert "data-session-id" not in result
    assert 'class="keep"' in result


# ---------------------------------------------------------------------------
# filter_jobs
# ---------------------------------------------------------------------------


def test_filter_jobs_removes_matching_titles() -> None:
    jobs = [
        JobListing(title="Cloud Solution Architect", url="https://x.com/1"),
        JobListing(title="Principal Cloud Solution Architect", url="https://x.com/2"),
        JobListing(title="Solution Engineer", url="https://x.com/3"),
    ]
    result = filter_jobs(jobs, ["Principal"])
    assert len(result) == 2
    assert all("Principal" not in j.title for j in result)


def test_filter_jobs_case_insensitive() -> None:
    jobs = [
        JobListing(title="VP of Engineering", url="https://x.com/1"),
        JobListing(title="Cloud Architect", url="https://x.com/2"),
    ]
    result = filter_jobs(jobs, ["vp"])
    assert len(result) == 1
    assert result[0].title == "Cloud Architect"


def test_filter_jobs_multiple_patterns() -> None:
    jobs = [
        JobListing(title="Director of Cloud", url="https://x.com/1"),
        JobListing(title="Principal Architect", url="https://x.com/2"),
        JobListing(title="Cloud Solution Architect", url="https://x.com/3"),
    ]
    result = filter_jobs(jobs, ["Director", "Principal"])
    assert len(result) == 1
    assert result[0].title == "Cloud Solution Architect"


def test_filter_jobs_empty_patterns_returns_all() -> None:
    jobs = [
        JobListing(title="Cloud Architect", url="https://x.com/1"),
        JobListing(title="Solution Engineer", url="https://x.com/2"),
    ]
    result = filter_jobs(jobs, [])
    assert result == jobs


def test_filter_jobs_no_matches_returns_all() -> None:
    jobs = [
        JobListing(title="Cloud Architect", url="https://x.com/1"),
    ]
    result = filter_jobs(jobs, ["Director"])
    assert result == jobs


def test_filter_jobs_empty_jobs_list() -> None:
    assert filter_jobs([], ["Principal"]) == []


def test_filter_jobs_all_filtered_returns_empty() -> None:
    jobs = [
        JobListing(title="Senior Architect", url="https://x.com/1"),
        JobListing(title="Distinguished Engineer", url="https://x.com/2"),
    ]
    result = filter_jobs(jobs, ["Senior", "Distinguished"])
    assert result == []


def test_filter_jobs_substring_match() -> None:
    """Substring matching — 'Lead' also matches 'Leader' and 'Leading'."""
    jobs = [
        JobListing(title="Team Leader", url="https://x.com/1"),
        JobListing(title="Leading Cloud Architect", url="https://x.com/2"),
        JobListing(title="Tech Lead", url="https://x.com/3"),
        JobListing(title="Cloud Architect", url="https://x.com/4"),
    ]
    result = filter_jobs(jobs, ["Lead"])
    assert len(result) == 1
    assert result[0].title == "Cloud Architect"


def test_filter_jobs_abbreviations() -> None:
    jobs = [
        JobListing(title="Sr. Cloud Architect", url="https://x.com/1"),
        JobListing(title="Cloud Architect", url="https://x.com/2"),
        JobListing(title="Dir. of Engineering", url="https://x.com/3"),
    ]
    result = filter_jobs(jobs, ["Sr.", "Dir."])
    assert len(result) == 1
    assert result[0].title == "Cloud Architect"


def test_filter_jobs_preserves_order() -> None:
    jobs = [
        JobListing(title="C Engineer", url="https://x.com/3"),
        JobListing(title="Senior A", url="https://x.com/1"),
        JobListing(title="B Architect", url="https://x.com/2"),
    ]
    result = filter_jobs(jobs, ["Senior"])
    assert [j.title for j in result] == ["C Engineer", "B Architect"]


def test_filter_jobs_pattern_with_spaces() -> None:
    jobs = [
        JobListing(title="Vice President of Engineering", url="https://x.com/1"),
        JobListing(title="Cloud Architect", url="https://x.com/2"),
    ]
    result = filter_jobs(jobs, ["Vice President"])
    assert len(result) == 1
    assert result[0].title == "Cloud Architect"


def test_filter_jobs_single_job_single_pattern() -> None:
    jobs = [JobListing(title="Senior Architect", url="https://x.com/1")]
    assert filter_jobs(jobs, ["Senior"]) == []
    assert filter_jobs(jobs, ["Junior"]) == jobs


def test_sanitize_debug_html_preserves_normal_content() -> None:
    html = "<h1>Job Title</h1><p>Description here</p>"
    assert sanitize_debug_html(html) == html


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_exceptions_hierarchy() -> None:
    assert issubclass(NoResultsError, CareerHubError)
    assert issubclass(ScrapeError, CareerHubError)
    assert issubclass(CareerHubError, Exception)
