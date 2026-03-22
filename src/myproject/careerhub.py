"""CareerHub browser automation — job search and application form filling."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from myproject.profile import Profile

logger = logging.getLogger(__name__)

CAREERHUB_BASE = "https://careerhub.microsoft.com"
CAREERHUB_JOBS = f"{CAREERHUB_BASE}/careerhub/explore/jobs"

_MAX_RETRIES = 2
_RETRY_BACKOFF_MS = 3000
_MAX_LOAD_MORE = 30


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CareerHubError(Exception):
    """Base exception for CareerHub automation errors."""


class NoResultsError(CareerHubError):
    """Search returned no results."""


class ScrapeError(CareerHubError):
    """Page scraping failed unexpectedly."""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class JobListing:
    """A single job result from CareerHub."""

    title: str
    url: str
    location: str = ""
    job_id: str = ""


# ---------------------------------------------------------------------------
# Pure Helpers (testable without a browser)
# ---------------------------------------------------------------------------


def _sanitize_for_selector(value: str) -> str:
    """Strip characters that could break or inject into CSS/Playwright selectors."""
    # SECURITY: prevent selector injection from profile.yaml values
    return (
        value.replace("\\", "")
        .replace('"', "")
        .replace("'", "")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _normalize_job_url(href: str) -> str:
    """Normalize a job link href to a full URL."""
    if href.startswith("http"):
        return href
    return f"{CAREERHUB_BASE}{href}"


def _extract_job_id(url: str) -> str:
    """Extract the job ID from a CareerHub job URL."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def _deduplicate_jobs(jobs: list[JobListing]) -> list[JobListing]:
    """Remove duplicate jobs by URL, preserving order."""
    seen: set[str] = set()
    unique: list[JobListing] = []
    for job in jobs:
        if job.url not in seen:
            seen.add(job.url)
            unique.append(job)
    return unique


def filter_jobs(
    jobs: list[JobListing],
    exclude_patterns: list[str],
) -> list[JobListing]:
    """Remove jobs whose title matches any exclude pattern (case-insensitive substring)."""
    if not exclude_patterns:
        return jobs

    lowered_patterns: list[str] = [p.lower() for p in exclude_patterns]
    kept: list[JobListing] = []
    for job in jobs:
        title_lower = job.title.lower()
        if any(pat in title_lower for pat in lowered_patterns):
            logger.debug("Filtered out: %r (matched exclude pattern)", job.title)
        else:
            kept.append(job)

    excluded_count = len(jobs) - len(kept)
    if excluded_count:
        logger.info("Filtered out %d jobs by title exclusion patterns", excluded_count)
    return kept


def _build_search_url(query: str) -> str:
    """Build a CareerHub search URL with properly encoded query."""
    return f"{CAREERHUB_JOBS}?q={quote_plus(query)}"


def sanitize_debug_html(html: str) -> str:
    """Strip <script> blocks and data-* attributes for safe debug dumps.

    Prevents accidental leakage of Azure AD tokens or session data.
    """
    # SECURITY: remove script blocks that could contain embedded tokens
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(
        r"""\s+data-[a-z0-9-]+=("[^"]*"|'[^']*'|\S+)""",
        "",
        html,
        flags=re.IGNORECASE,
    )
    return html


# ---------------------------------------------------------------------------
# Job Search
# ---------------------------------------------------------------------------


def search_jobs(page: Page, profile: Profile) -> list[JobListing]:
    """Search CareerHub for jobs matching the profile's target titles.

    Returns a deduplicated list of JobListing objects.
    """
    results: list[JobListing] = []

    queries = _build_search_queries(profile)
    for query in queries:
        logger.info("Searching: %s (location: %s)", query, profile.search_location or "<any>")
        found = _search_one_query_with_retry(page, query, profile.search_location)
        results.extend(found)

    results = _deduplicate_jobs(results)
    pre_filter_count = len(results)
    results = filter_jobs(results, profile.exclude_title_patterns)
    filtered_count = pre_filter_count - len(results)
    logger.info(
        "Found %d jobs, filtered %d by title exclusion, %d remaining",
        pre_filter_count,
        filtered_count,
        len(results),
    )
    return results


def _build_search_queries(profile: Profile) -> list[str]:
    """Return target titles as search queries (no keyword combos)."""
    return list(profile.target_titles)


def _search_one_query_with_retry(
    page: Page,
    query: str,
    location: str = "",
) -> list[JobListing]:
    """Execute a search query with retry on transient failures."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            jobs = _search_one_query(page, query, location)
            if jobs:
                return jobs
            if _has_no_results_indicator(page):
                logger.info("No results for: %s", query)
                return []
            # Empty without indicator — possible timing issue
            if attempt < _MAX_RETRIES:
                logger.debug("Empty results, retrying (%d/%d)...", attempt + 1, _MAX_RETRIES)
                page.wait_for_timeout(_RETRY_BACKOFF_MS * (attempt + 1))
                continue
            return []
        except PlaywrightTimeout as exc:
            if attempt < _MAX_RETRIES:
                logger.warning("Search attempt %d failed: %s — retrying", attempt + 1, exc)
                page.wait_for_timeout(_RETRY_BACKOFF_MS * (attempt + 1))
            else:
                logger.error("Search failed after %d attempts: %s", _MAX_RETRIES + 1, exc)
                return []
    return []  # unreachable but satisfies mypy


def _search_one_query(
    page: Page,
    query: str,
    location: str = "",
) -> list[JobListing]:
    """Execute a single search query and scrape the results."""
    page.goto(CAREERHUB_JOBS, wait_until="domcontentloaded")
    _wait_for_spa_idle(page)

    search_input = page.locator(
        'input#main-search-box, input[placeholder="Search by job title, ID, or keyword"]'
    ).first
    try:
        search_input.wait_for(state="visible", timeout=20000)

        # Clear and type search field character-by-character (SPA ignores .fill())
        search_input.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)
        search_input.press_sequentially(query, delay=50)

        # Fill location field if provided
        if location:
            try:
                location_input = page.locator(
                    'input#location-search-box, input[placeholder="City, state, or country/region"]'
                ).first
                location_input.wait_for(state="visible", timeout=10000)
                location_input.click()
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                page.wait_for_timeout(300)
                location_input.press_sequentially(location, delay=50)
                # Press Enter to confirm the autocomplete selection
                page.wait_for_timeout(2000)
                page.keyboard.press("Enter")
                page.wait_for_timeout(500)
            except PlaywrightTimeout:
                logger.warning("Location input not found — searching without location filter")

        # Click the "Go" button
        go_btn = page.locator('button:has-text("Go"), button[aria-label="Go"]').first
        go_btn.click(timeout=5000)

        # Post-search settling — wait for job cards to actually appear
        _wait_for_spa_idle(page)
        _wait_for_job_cards(page, timeout_ms=20000)
    except PlaywrightTimeout:
        logger.warning("Could not find search input — trying URL-based search")
        page.goto(_build_search_url(query), wait_until="domcontentloaded")
        _wait_for_spa_idle(page)
        _wait_for_job_cards(page, timeout_ms=20000)

    # Phase 1: Load ALL results by clicking "Load More Results" repeatedly
    _load_all_results(page)

    # Phase 2: Scrape all visible cards at once
    jobs = _scrape_job_cards(page)
    return _deduplicate_jobs(jobs)


def _wait_for_job_cards(page: Page, timeout_ms: int = 20000) -> None:
    """Poll until at least one job card link appears in the DOM."""
    poll_ms = 1000
    elapsed = 0
    selector = '.common-entity-card-container, a[href*="/careerhub/explore/jobs/"]'
    while elapsed < timeout_ms:
        count = page.locator(selector).count()
        if count > 0:
            logger.debug("Found %d job card elements after %dms", count, elapsed)
            # Give a bit more time for all cards to render
            page.wait_for_timeout(2000)
            return
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    logger.warning("No job cards appeared after %dms", timeout_ms)


def _has_no_results_indicator(page: Page) -> bool:
    """Check if the page shows a 'no results' message."""
    patterns = [
        "text=/no (matching )?results/i",
        "text=/no jobs found/i",
        ".no-results-message",
    ]
    for pattern in patterns:
        try:
            if page.locator(pattern).first.is_visible(timeout=1000):
                return True
        except PlaywrightTimeout:
            continue
    return False


def _scroll_results_panel(page: Page) -> None:
    """Scroll the sidebar job-results panel to its bottom.

    The job list lives in a scrollable container, not the main page body.
    Tries common container selectors, falls back to page-level scroll.
    """
    scrolled = page.evaluate("""() => {
        // Try known sidebar containers for CareerHub / Eightfold
        const selectors = [
            '.cards-container',
            '.cards-container-scroll-handler',
            '.results-list',
            '[class*="results-list"]',
            '[class*="job-list"]',
            '[class*="JobList"]',
            '[role="list"]',
            '[class*="search-results"]',
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.scrollHeight > el.clientHeight) {
                el.scrollTop = el.scrollHeight;
                return true;
            }
        }
        // Heuristic: walk up from first job card to find scrollable ancestor
        const card = document.querySelector('.common-entity-card-container');
        if (card) {
            let parent = card.parentElement;
            while (parent && parent !== document.body) {
                if (parent.scrollHeight > parent.clientHeight + 50) {
                    parent.scrollTop = parent.scrollHeight;
                    return true;
                }
                parent = parent.parentElement;
            }
        }
        // Fallback: scroll the page body
        window.scrollTo(0, document.body.scrollHeight);
        return false;
    }""")
    if scrolled:
        logger.debug("Scrolled sidebar results panel")
    else:
        logger.debug("Fell back to page-level scroll for Load More")


def _load_all_results(page: Page) -> None:
    """Repeatedly click 'Load More Results' until exhausted or cap reached."""
    for i in range(_MAX_LOAD_MORE):
        card_count = page.locator(".common-entity-card-container").count()
        logger.debug("Load More iteration %d — %d cards so far", i + 1, card_count)
        if not _load_more_results(page):
            break
    total = page.locator(".common-entity-card-container").count()
    logger.info("All results loaded: %d total cards", total)


def _load_more_results(page: Page) -> bool:
    """Scroll to bottom, wait for lazy button render, then click 'Load More'.

    The Load More button only appears in the DOM after the sidebar is scrolled
    to the bottom. We scroll first, then use Playwright's auto-wait to detect
    the button once React renders it.

    Returns True if more results were loaded (verified by card count).
    """
    card_count_before = page.locator(".common-entity-card-container").count()

    # Step 1: Scroll the sidebar to the bottom so the button lazily renders.
    _scroll_results_panel(page)

    # Step 2: Wait for the Load More button to appear.
    # Playwright's wait_for() auto-polls the DOM — no fixed sleep needed.
    load_more = page.locator(".load-more-button")
    try:
        load_more.wait_for(state="visible", timeout=5000)
        logger.debug("Load More button appeared (.load-more-button)")
    except PlaywrightTimeout:
        # Try text-based fallback
        load_more = page.get_by_text("Load More Results", exact=True)
        try:
            load_more.wait_for(state="visible", timeout=3000)
            logger.debug("Load More button appeared (text match)")
        except PlaywrightTimeout:
            logger.debug("Load More button did not appear after scroll")
            return False

    # Step 3: Click the button.
    try:
        load_more.scroll_into_view_if_needed()
        load_more.click()
        logger.debug("Clicked Load More button")
    except PlaywrightTimeout:
        logger.debug("Load More button found but click failed")
        return False

    # Step 4: Wait for new cards to load — poll until count increases.
    poll_interval = 500
    max_wait = 10000
    elapsed = 0
    while elapsed < max_wait:
        page.wait_for_timeout(poll_interval)
        elapsed += poll_interval
        card_count_after = page.locator(".common-entity-card-container").count()
        if card_count_after > card_count_before:
            logger.debug(
                "Load More success: %d -> %d cards (waited %dms)",
                card_count_before,
                card_count_after,
                elapsed,
            )
            return True

    logger.debug(
        "Load More clicked but no new cards after %dms (%d cards)",
        max_wait,
        page.locator(".common-entity-card-container").count(),
    )
    return False


def _scrape_job_cards(page: Page) -> list[JobListing]:
    """Extract job listings from the current search results page."""
    # Use JavaScript to extract directly from the live DOM — more reliable
    # than Playwright locators for dynamically-rendered React cards.
    raw_jobs: list[dict[str, str]] = page.evaluate("""() => {
        const jobs = [];
        const seen = new Set();

        // Strategy 1: card containers with <a> hrefs (classic layout)
        const cards = document.querySelectorAll('.common-entity-card-container');
        for (const card of cards) {
            const link = card.querySelector(
                'a.card-linkout[href*="/careerhub/explore/jobs/"]'
            ) || card.querySelector(
                'a[href*="/careerhub/explore/jobs/"]'
            );
            if (!link) continue;
            const href = link.getAttribute('href') || '';
            if (!href.includes('/careerhub/explore/jobs/')) continue;
            let title = '';
            const titleEl = card.querySelector('.job-card-title, .job-card-header h3, h3');
            if (titleEl) title = titleEl.textContent.trim();
            if (!title) {
                const h3 = link.querySelector('h3');
                if (h3) title = h3.textContent.trim();
            }
            if (!title) continue;
            seen.add(href);
            jobs.push({ title, href });
        }

        // Strategy 2: cards WITHOUT <a> hrefs (enableLink: false / SPA click handlers)
        if (jobs.length === 0 && cards.length > 0) {
            for (const card of cards) {
                let title = '';
                const titleEl = card.querySelector('.job-card-title, .job-card-header h3, h3');
                if (titleEl) title = titleEl.textContent.trim();
                if (!title) continue;
                // Try to find ANY anchor inside the card
                let href = '';
                const anyLink = card.querySelector('a[href*="/careerhub/"]')
                    || card.querySelector('a[href]');
                if (anyLink) {
                    href = anyLink.getAttribute('href') || '';
                }
                // Try data attributes that Eightfold may set
                if (!href) {
                    const jobId = card.getAttribute('data-job-id')
                        || card.getAttribute('data-entity-id')
                        || card.getAttribute('data-id');
                    if (jobId) href = '/careerhub/explore/jobs/' + jobId;
                }
                // Last resort: construct from the inner card's click target
                if (!href) {
                    const clickable = card.querySelector('.common-entity-card, .card-linkout');
                    if (clickable) {
                        const cHref = clickable.getAttribute('href')
                            || clickable.getAttribute('data-href');
                        if (cHref) href = cHref;
                    }
                }
                if (href && !seen.has(href)) {
                    seen.add(href);
                    jobs.push({ title, href });
                }
            }
        }

        // Strategy 3: direct link scan (no card containers at all)
        if (jobs.length === 0) {
            const links = document.querySelectorAll('a[href*="/careerhub/explore/jobs/"]');
            for (const link of links) {
                const href = link.getAttribute('href') || '';
                if (!href.includes('/careerhub/explore/jobs/')) continue;
                const parts = href.split('/');
                const lastPart = parts[parts.length - 1] || parts[parts.length - 2];
                if (!lastPart || lastPart === 'jobs' || lastPart === 'explore') continue;
                if (seen.has(href)) continue;
                const title = link.textContent.trim().split('\\n')[0].trim();
                if (title) {
                    seen.add(href);
                    jobs.push({ title, href });
                }
            }
        }

        return jobs;
    }""")

    logger.debug("JavaScript extracted %d raw job entries from DOM", len(raw_jobs))

    # If JS found 0 jobs but cards exist, try a click-based fallback
    if not raw_jobs:
        card_count = page.locator(".common-entity-card-container").count()
        if card_count > 0:
            logger.warning(
                "JS extracted 0 jobs from %d cards — trying click-based extraction",
                card_count,
            )
            # Dump the first card's HTML for debugging
            try:
                sample = page.locator(".common-entity-card-container").first.inner_html(
                    timeout=3000
                )
                logger.debug("First card HTML (500 chars): %s", sample[:500])
            except PlaywrightTimeout:
                pass

            # Click-based fallback: click each card, read the URL, go back
            raw_jobs = _extract_jobs_by_clicking(page, card_count)

    seen_urls: set[str] = set()
    jobs: list[JobListing] = []
    for entry in raw_jobs:
        href = entry.get("href", "")
        title = entry.get("title", "")
        if not href or not title:
            continue
        url = _normalize_job_url(href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = title.split("\n")[0].strip()
        job_id = _extract_job_id(url)
        jobs.append(JobListing(title=title, url=url, job_id=job_id))

    logger.info("Scraped %d unique job cards", len(jobs))
    return jobs


def _extract_jobs_by_clicking(page: Page, card_count: int) -> list[dict[str, str]]:
    """Fallback: click each card in the sidebar to read the URL from the address bar.

    CareerHub renders a split view — left sidebar has job cards, right panel has
    detail. Clicking a card updates the right panel AND changes the URL in the
    address bar to the job's detail URL. The sidebar stays intact.
    """
    jobs: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    logger.info("Clicking through %d cards to extract job URLs...", card_count)

    for i in range(card_count):
        if i > 0 and i % 25 == 0:
            logger.info(
                "  ... clicked %d/%d cards (%d jobs found so far)", i, card_count, len(jobs)
            )
        try:
            cards = page.locator(".common-entity-card-container")
            current_count = cards.count()
            if current_count <= i:
                logger.debug("Only %d cards available, stopping at index %d", current_count, i)
                break

            card = cards.nth(i)

            # Get the title from the card's h3 BEFORE clicking
            title = ""
            try:
                title_el = card.locator("h3").first
                title = title_el.inner_text(timeout=2000).strip()
            except PlaywrightTimeout:
                pass
            if not title:
                continue

            # Click the card — this loads the detail in the right panel
            # and updates the browser URL to the job's detail page
            old_url = page.url
            try:
                card.click(timeout=3000)
            except PlaywrightTimeout:
                # Click may have worked even though Playwright timed out
                # waiting for the element to "settle" — check URL anyway
                logger.debug("Card %d click timed out — checking URL anyway", i)

            # Poll for URL change instead of fixed 1.5s wait
            # SPA pushState fires in ~200-400ms — polling at 50ms catches it fast
            url_changed = False
            for _ in range(60):  # 60 × 50ms = 3s max
                page.wait_for_timeout(50)
                if page.url != old_url:
                    url_changed = True
                    break

            if not url_changed:
                continue

            # Read the URL from the address bar
            current_url = page.url
            if "/careerhub/explore/jobs/" in current_url:
                # Extract the path part (remove the domain)
                href = current_url
                if "careerhub.microsoft.com" in href:
                    href = href.split("careerhub.microsoft.com", 1)[1]

                if href not in seen_urls:
                    seen_urls.add(href)
                    jobs.append({"title": title, "href": href})
                    logger.debug("Card %d: %s -> %s", i, title[:60], href)

        except (PlaywrightTimeout, Exception) as exc:
            logger.debug("Click extraction failed for card %d: %s", i, exc)
            continue

    logger.info("Click-based extraction found %d jobs from %d cards", len(jobs), card_count)
    return jobs


def _wait_for_spa_idle(page: Page, timeout_ms: int = 20000) -> None:
    """Wait for the CareerHub SPA to finish loading.

    Tries network-idle first, then spinner detection, then a fixed delay.
    """
    # Best signal: wait for network to go quiet
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
        return
    except PlaywrightTimeout:
        pass

    # Fallback: watch for spinners
    spinner_selectors = [
        ".page-spinner-wrapper",
        "[class*='spinner-module_spinner']",
        ".spinner",
        "[class*='Spinner']",
    ]

    for sel in spinner_selectors:
        spinner = page.locator(sel).first
        try:
            spinner.wait_for(state="visible", timeout=2000)
            spinner.wait_for(state="hidden", timeout=timeout_ms)
            logger.debug("Spinner '%s' appeared and disappeared", sel)
            return
        except PlaywrightTimeout:
            continue

    # No spinner detected — give the SPA a generous settling period
    page.wait_for_timeout(5000)


# ---------------------------------------------------------------------------
# Form Filling
# ---------------------------------------------------------------------------


def fill_application(page: Page, profile: Profile, job: JobListing) -> Page:
    """Navigate to a job's application page and fill out the form.

    Returns the active page (may differ from input if Apply opened a new tab).
    """
    logger.info("Opening application for: %s", job.title)
    page.goto(job.url, wait_until="domcontentloaded")
    _wait_for_spa_idle(page)

    # Click "Apply" — may open a new tab
    page = _click_apply_button(page)
    _wait_for_spa_idle(page)

    # Fill each section
    _fill_contact_info(page, profile)
    _select_resume(page, profile)
    _fill_work_authorization(page, profile)
    _fill_candidate_questions(page, profile)
    _fill_job_specific_questions(page, profile)
    _fill_acknowledgments(page, profile)

    logger.info(
        "Form filled for '%s'. Review the form and click Submit manually.",
        job.title,
    )
    return page


def _click_apply_button(page: Page) -> Page:
    """Click the Apply button on the job detail page.

    Returns the page to continue with — may be a new tab if Apply opened one.
    """
    apply_selectors = [
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        '[data-testid*="apply"]',
        'button:has-text("Apply now")',
    ]
    for selector in apply_selectors:
        btn = page.locator(selector).first
        try:
            if btn.is_visible(timeout=3000):
                # Apply may open a new tab (popup)
                try:
                    with page.expect_popup(timeout=3000) as popup_info:
                        btn.click()
                    new_page = popup_info.value
                    new_page.wait_for_load_state("domcontentloaded")
                    logger.info("Apply opened in new tab — switching")
                    return new_page
                except PlaywrightTimeout:
                    # Stayed on same page — that's normal
                    return page
        except PlaywrightTimeout:
            continue
    logger.warning("Could not find Apply button — may already be on the form")
    return page


def _fill_contact_info(page: Page, profile: Profile) -> None:
    """Fill in contact information fields (only if editable)."""
    field_map = {
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "email": profile.email,
        "phone": profile.phone,
        "address": profile.address,
        "city": profile.city,
        "state": profile.state,
        "postal_code": profile.postal_code,
    }

    for field_name, value in field_map.items():
        if not value:
            continue
        _try_fill_field(page, field_name, value)

    if profile.address_line_2:
        _try_fill_field(page, "address_line_2", profile.address_line_2)


def _try_fill_field(page: Page, field_hint: str, value: str) -> None:
    """Try to fill a text field by matching name/label/placeholder patterns."""
    label_patterns = {
        "first_name": ["First Name", "Preferred First"],
        "last_name": ["Last Name", "Preferred Last"],
        "email": ["Email"],
        "phone": ["Phone"],
        "address": ["Address"],
        "address_line_2": ["Address Line 2"],
        "city": ["City"],
        "state": ["State"],
        "postal_code": ["Postal", "Zip"],
    }

    patterns = label_patterns.get(field_hint, [field_hint])

    for pattern in patterns:
        safe_pattern = _sanitize_for_selector(pattern)
        try:
            label = page.locator(f'label:has-text("{safe_pattern}")').first
            if label.is_visible(timeout=1000):
                label_for = label.get_attribute("for")
                if label_for:
                    input_el = page.locator(f"#{_sanitize_for_selector(label_for)}")
                else:
                    parent = label.locator("xpath=..")
                    input_el = parent.locator("input, select, textarea").first

                if input_el.is_visible(timeout=1000):
                    if input_el.is_editable(timeout=1000):
                        input_el.fill(value)
                        logger.debug("Filled '%s'", field_hint)
                        return
                    logger.debug(
                        "Field '%s' visible but not editable (pre-filled)",
                        field_hint,
                    )
                    return
        except (PlaywrightTimeout, Exception):
            continue

    # Fallback: placeholder/name/aria-label matching
    safe_hint = _sanitize_for_selector(field_hint)
    for pattern in patterns:
        safe_pattern = _sanitize_for_selector(pattern)
        selectors = [
            f'input[placeholder*="{safe_pattern}" i]',
            f'input[name*="{safe_hint}" i]',
            f'input[aria-label*="{safe_pattern}" i]',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    if el.is_editable(timeout=1000):
                        el.fill(value)
                        logger.debug("Filled '%s' via selector", field_hint)
                        return
                    logger.debug(
                        "Field '%s' visible but not editable (pre-filled)",
                        field_hint,
                    )
                    return
            except (PlaywrightTimeout, Exception):
                continue

    logger.debug("Field '%s' not found or not editable (may be pre-filled)", field_hint)


def _select_resume(page: Page, profile: Profile) -> None:
    """Select the resume from the dropdown if available."""
    if not profile.resume_name:
        return

    safe_name = _sanitize_for_selector(profile.resume_name)
    try:
        resume_selectors = [
            'select:near(:text("Resume"))',
            'select[aria-label*="Resume" i]',
            'select[name*="resume" i]',
        ]
        for sel in resume_selectors:
            dropdown = page.locator(sel).first
            try:
                if dropdown.is_visible(timeout=2000):
                    dropdown.select_option(label=profile.resume_name)
                    logger.info("Selected resume: %s", profile.resume_name)
                    return
            except (PlaywrightTimeout, Exception):
                continue

        # Try clicking a dropdown-style component (non-native select)
        resume_dropdown = page.locator(
            f'[role="listbox"] >> text="{safe_name}",[role="option"]:has-text("{safe_name}")'
        ).first
        if resume_dropdown.is_visible(timeout=2000):
            resume_dropdown.click()
            logger.info("Selected resume via dropdown: %s", profile.resume_name)
    except (PlaywrightTimeout, Exception):
        logger.debug("Resume dropdown not found or already selected")


def _fill_work_authorization(page: Page, profile: Profile) -> None:
    """Fill work authorization dropdowns."""
    _select_dropdown_near_text(
        page,
        "legally authorized to work",
        profile.legally_authorized,
    )
    _select_dropdown_near_text(
        page,
        "require the company's sponsorship",
        profile.needs_sponsorship,
    )


def _fill_candidate_questions(page: Page, profile: Profile) -> None:
    """Fill candidate question dropdowns."""
    _select_dropdown_near_text(
        page,
        "member of the military",
        profile.military_or_government,
    )


def _fill_job_specific_questions(page: Page, profile: Profile) -> None:
    """Click radio buttons for job-specific questions."""
    _click_radio_near_text(
        page,
        "will you now or in the future require",
        profile.needs_visa_sponsorship,
    )
    _click_radio_near_text(
        page,
        "Bachelor's Degree",
        profile.meets_degree_requirement,
    )


def _fill_acknowledgments(page: Page, profile: Profile) -> None:
    """Check all acknowledgment checkboxes."""
    checkbox_texts = [
        "you possess certain minimum required qualifications",
        "Microsoft Data Privacy Notice",
        "candidate code of conduct",
    ]
    should_check = [
        profile.acknowledge_qualifications,
        profile.acknowledge_privacy_notice,
        profile.acknowledge_code_of_conduct,
    ]

    for text, check in zip(checkbox_texts, should_check):
        if not check:
            continue
        try:
            section = page.locator(f'text="{text}"').first
            if section.is_visible(timeout=2000):
                checkbox = (
                    section.locator("xpath=ancestor::*[.//input[@type='checkbox']]")
                    .locator("input[type='checkbox']")
                    .first
                )
                if not checkbox.is_checked():
                    checkbox.check()
                    logger.debug("Checked acknowledgment: %s", text[:40])
        except (PlaywrightTimeout, Exception):
            try:
                label = page.locator(f'label:has-text("{text}")').first
                if label.is_visible(timeout=1000):
                    label.click()
                    logger.debug("Checked via label click: %s", text[:40])
            except (PlaywrightTimeout, Exception):
                logger.warning("Could not check: %s", text[:40])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_dropdown_near_text(page: Page, question_text: str, value: str) -> None:
    """Find a <select> near a question's text and choose the given value."""
    safe_value = _sanitize_for_selector(value)
    try:
        question = page.locator(f"text=/{question_text}/i").first
        if not question.is_visible(timeout=3000):
            logger.debug("Question not found: %s", question_text[:50])
            return

        container = question.locator("xpath=ancestor::*[.//select]").first
        select_el = container.locator("select").first

        if select_el.is_visible(timeout=2000):
            select_el.select_option(label=value)
            logger.info("Selected '%s' for: %s", value, question_text[:50])
            return
    except (PlaywrightTimeout, Exception):
        pass

    # Fallback: custom dropdown (div-based)
    try:
        question = page.locator(f"text=/{question_text}/i").first
        container = question.locator("xpath=ancestor::*[.//select or .//*[@role='listbox']]").first
        trigger = container.locator(
            'select, [role="combobox"], [role="listbox"], [class*="dropdown"], [class*="select"]'
        ).first
        trigger.click()
        page.wait_for_timeout(500)
        option = page.locator(f'[role="option"]:has-text("{safe_value}")').first
        if option.is_visible(timeout=2000):
            option.click()
            logger.info("Selected '%s' via custom dropdown", value)
    except (PlaywrightTimeout, Exception):
        logger.warning("Could not select dropdown for: %s", question_text[:50])


def _click_radio_near_text(page: Page, question_text: str, value: str) -> None:
    """Find a radio button group near a question and select the value."""
    safe_value = _sanitize_for_selector(value)
    try:
        question = page.locator(f"text=/{question_text}/i").first
        if not question.is_visible(timeout=3000):
            logger.debug("Radio question not found: %s", question_text[:50])
            return

        container = question.locator("xpath=ancestor::*[.//input[@type='radio']]").first

        radio_label = container.locator(f'label:has-text("{safe_value}")').first
        if radio_label.is_visible(timeout=2000):
            radio_label.click()
            logger.info("Selected radio '%s' for: %s", value, question_text[:50])
            return

        radio = container.locator(
            f'input[type="radio"][value="{safe_value}" i],'
            f'input[type="radio"] + label:has-text("{safe_value}")'
        ).first
        if radio.is_visible(timeout=2000):
            radio.click()
            logger.info("Selected radio '%s' via input", value)
    except (PlaywrightTimeout, Exception):
        logger.warning("Could not select radio for: %s", question_text[:50])


def scroll_to_bottom(page: Page) -> None:
    """Scroll to the bottom of the page."""
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(500)


def export_results_to_file(
    jobs: list[JobListing],
    query: str,
    location: str,
    output_path: str | Path = "results.txt",
) -> Path:
    """Write job search results to a text file.

    Args:
        jobs: List of job listings to export.
        query: The search query used.
        location: The location filter used.
        output_path: File path for the output (default: results.txt).

    Returns:
        The resolved Path where results were written.
    """
    path = Path(output_path)
    lines: list[str] = [
        "CareerHub Job Search Results",
        f"Date: {date.today().isoformat()}",
        f"Search: {query} | Location: {location or 'Any'}",
        "=" * 60,
        "",
    ]
    for i, job in enumerate(jobs, 1):
        lines.append(f"{i}. {job.title}")
        lines.append(f"   {job.url}")
        lines.append("")
    lines.append(f"Total: {len(jobs)} matching jobs")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Exported %d results to %s", len(jobs), path.resolve())
    return path
