"""CLI for CareerHub auto-apply tool."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from myproject.careerhub import (
    JobListing,
    export_results_to_file,
    fill_application,
    scroll_to_bottom,
    search_jobs,
)
from myproject.profile import load_profile

logger = logging.getLogger("myproject")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="careerhub-apply",
        description="Search CareerHub for matching jobs and auto-fill applications.",
    )
    p.add_argument(
        "--profile",
        type=Path,
        default=Path("profile.yaml"),
        help="Path to profile YAML config (default: profile.yaml)",
    )
    p.add_argument(
        "--search-only",
        action="store_true",
        help="Only search for jobs — don't open applications.",
    )
    p.add_argument(
        "--job-url",
        type=str,
        help="Skip search — fill the application for this specific job URL.",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (not recommended — you need to review forms).",
    )
    p.add_argument(
        "--auto-apply",
        action="store_true",
        help="Skip the per-job [y/n/q] prompt — apply to all matching jobs.",
    )
    p.add_argument(
        "--max-applications",
        type=int,
        default=10,
        help="Maximum applications per run (default: 10, hard ceiling: 25).",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    p.add_argument(
        "--debug-dump",
        action="store_true",
        help="Dump page HTML to debug/ folder after auth — for fixing selectors.",
    )
    return p.parse_args()


def main() -> None:
    """Entry point for the CareerHub auto-apply CLI."""
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load profile
    try:
        profile = load_profile(args.profile)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info("Loaded profile for %s %s", profile.first_name, profile.last_name)
    logger.info("Target titles: %s", ", ".join(profile.target_titles))
    if profile.search_location:
        logger.info("Search location: %s", profile.search_location)
    if profile.exclude_title_patterns:
        logger.info("Excluding titles matching: %s", ", ".join(profile.exclude_title_patterns))

    # Persistent browser data dir — keeps SSO cookies between runs
    user_data_dir = Path(".browser-data")
    user_data_dir.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        # Persistent context = real browser profile with saved cookies/auth
        # After first login, subsequent runs skip SSO entirely
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=args.headless,
            channel="msedge",
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Navigate to CareerHub — user may need to authenticate
        logger.info("Opening CareerHub — you may need to sign in via SSO...")
        page.goto("https://careerhub.microsoft.com", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        # Check if we need to wait for auth
        if "login" in page.url.lower() or "adfs" in page.url.lower() or "fido" in page.url.lower():
            logger.info(
                "SSO login detected. Please sign in manually in the browser.\n"
                "  Complete the FIDO/security key prompt if it appears.\n"
                "  The script will wait up to 2 minutes for you to finish."
            )
            # Poll instead of wait_for_url — survives page closes and redirects
            deadline = time.time() + 120
            while time.time() < deadline:
                time.sleep(2)
                try:
                    current_url = page.url
                except Exception:
                    # Page may have been replaced — get the new one
                    pages = context.pages
                    if pages:
                        page = pages[-1]
                        current_url = page.url
                    else:
                        continue
                if "careerhub" in current_url.lower() and "login" not in current_url.lower():
                    logger.info("Authenticated successfully.")
                    break
            else:
                logger.error("Timed out waiting for SSO. Run again — your cookies are saved.")
                context.close()
                sys.exit(1)

        if args.debug_dump:
            _dump_pages(page, args.job_url)
            context.close()
            return

        # Track collected jobs for export on success or browser close
        collected_jobs: list[JobListing] = []
        search_query = ", ".join(profile.target_titles)
        search_location = profile.search_location or ""

        try:
            if args.job_url:
                # Direct application to a specific job
                job = JobListing(title="Direct Application", url=args.job_url)
                page = fill_application(page, profile, job)
                scroll_to_bottom(page)
                _wait_for_user_review(page)

            elif args.search_only:
                # Just search, print results
                jobs = search_jobs(page, profile)
                collected_jobs = jobs
                if not jobs:
                    logger.info("No matching jobs found.")
                else:
                    print(f"\n{'=' * 60}")
                    print(f" Found {len(jobs)} matching jobs")
                    print(f"{'=' * 60}")
                    for i, job in enumerate(jobs, 1):
                        print(f"  {i}. {job.title}")
                        print(f"     {job.url}")
                    print()

            else:
                # Full flow: search then apply
                jobs = search_jobs(page, profile)
                collected_jobs = jobs
                if not jobs:
                    logger.info("No matching jobs found.")
                    context.close()
                    return

                print(f"\n{'=' * 60}")
                print(f" Found {len(jobs)} matching jobs")
                print(f"{'=' * 60}")
                for i, job in enumerate(jobs, 1):
                    print(f"  {i}. {job.title}")
                    print(f"     {job.url}")
                print()

                _MAX_AUTO_APPLY = 25
                effective_max = min(args.max_applications, _MAX_AUTO_APPLY)
                applied_count = 0

                for i, job in enumerate(jobs, 1):
                    if args.auto_apply and applied_count >= effective_max:
                        logger.warning(
                            "Reached max applications (%d). Stopping.",
                            effective_max,
                        )
                        break

                    print(f"\n--- Job {i}/{len(jobs)}: {job.title} ---")

                    if not args.auto_apply:
                        choice = input("Apply to this job? [y/n/q(uit)]: ").strip().lower()
                        if choice == "q":
                            break
                        if choice != "y":
                            continue

                    try:
                        page = fill_application(page, profile, job)
                        scroll_to_bottom(page)
                        applied_count += 1
                    except Exception:
                        logger.exception("Failed to fill application for: %s", job.title)
                        continue

                    if not args.auto_apply:
                        _wait_for_user_review(page)

                logger.info("Applied to %d jobs this run.", applied_count)

        except Exception as exc:
            # Catch browser-disconnected / target-closed errors from Playwright
            exc_name = type(exc).__name__
            if "TargetClosed" in exc_name or "closed" in str(exc).lower():
                logger.info("Browser was closed by user.")
            else:
                logger.exception("Unexpected error during run.")
        finally:
            # Always export whatever results we collected
            if collected_jobs:
                export_results_to_file(
                    collected_jobs,
                    search_query,
                    search_location,
                )
            try:
                context.close()
            except Exception:
                pass  # browser already closed

    logger.info("Done.")


def _wait_for_user_review(page: object) -> None:
    """Pause and let the user review the filled form."""
    print("\n" + "=" * 60)
    print(" FORM FILLED — REVIEW BEFORE SUBMITTING")
    print(" The browser is open. Review the form, then:")
    print("   - Click 'Submit application' in the browser if everything looks good")
    print("   - Or press Enter here to continue to the next job")
    print("=" * 60)
    input("\nPress Enter to continue...")


def _dump_pages(page: "Page", job_url: str | None) -> None:  # type: ignore[name-defined]
    """Dump page HTML to debug/ folder so we can inspect the real DOM."""
    from pathlib import Path as P

    from myproject.careerhub import sanitize_debug_html

    debug_dir = P("debug")
    debug_dir.mkdir(exist_ok=True)

    # Dump 1: the CareerHub landing / jobs listing
    logger.info("Dumping CareerHub landing page...")
    page.goto(
        "https://careerhub.microsoft.com/careerhub/explore/jobs", wait_until="domcontentloaded"
    )
    page.wait_for_timeout(5000)
    # SECURITY: sanitize HTML before writing — strips tokens/session data
    (debug_dir / "01_jobs_listing.html").write_text(
        sanitize_debug_html(page.content()), encoding="utf-8"
    )
    page.screenshot(path=str(debug_dir / "01_jobs_listing.png"), full_page=True)
    logger.info("  Saved: debug/01_jobs_listing.html + .png")

    # Dump 2: the specific job page (if provided)
    if job_url:
        logger.info("Dumping job detail page...")
        page.goto(job_url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        (debug_dir / "02_job_detail.html").write_text(
            sanitize_debug_html(page.content()), encoding="utf-8"
        )
        page.screenshot(path=str(debug_dir / "02_job_detail.png"), full_page=True)
        logger.info("  Saved: debug/02_job_detail.html + .png")

        # Try clicking Apply
        apply_btns = page.locator('button:has-text("Apply"), a:has-text("Apply")').all()
        if apply_btns:
            logger.info("  Found %d Apply button(s) — clicking first one...", len(apply_btns))
            apply_btns[0].click()
            page.wait_for_timeout(5000)
            (debug_dir / "03_application_form.html").write_text(
                sanitize_debug_html(page.content()), encoding="utf-8"
            )
            page.screenshot(path=str(debug_dir / "03_application_form.png"), full_page=True)
            logger.info("  Saved: debug/03_application_form.html + .png")
        else:
            logger.info("  No Apply button found on detail page")

    print(f"\nDebug files saved to: {debug_dir.resolve()}")
    print("Share the screenshots or HTML with me so I can fix the selectors.")


if __name__ == "__main__":
    main()
