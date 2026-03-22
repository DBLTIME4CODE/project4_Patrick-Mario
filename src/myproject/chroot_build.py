"""Clean chroot kernel compilation using debootstrap.

Provides an isolated build environment for compiling Linux kernels,
avoiding host contamination and ensuring reproducible builds.
Integrates with :mod:`myproject.kernel_builder` for shared validation,
subprocess helpers, and build dependency lists.
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
from collections.abc import Generator
from pathlib import Path

from myproject.kernel_builder import (
    BUILD_DEPS,
    BuildError,
    ValidationError,
    run_cmd,
    validate_input,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHROOT_MOUNT_POINTS: tuple[tuple[str, str, str], ...] = (
    ("proc", "proc", "/proc"),
    ("sysfs", "sysfs", "/sys"),
    ("devtmpfs", "udev", "/dev"),
)
"""(fs_type, source, mount_target) tuples — mounted in order, unmounted in reverse."""

DEFAULT_SUITE: str = "bookworm"
DEFAULT_MIRROR: str = "http://deb.debian.org/debian"

# Additional packages needed inside chroot beyond BUILD_DEPS
CHROOT_EXTRA_PACKAGES: list[str] = ["locales", "sudo"]

_MIN_CHROOT_DEPTH: int = 3
"""Minimum path depth for rm -rf safety (e.g. /tmp/myproject/chroot)."""

_SAFE_GLOB_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_.*?\-\[\]]+$")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_suite(suite: str) -> str:
    """Validate a debootstrap suite name (e.g. 'bookworm', 'jammy')."""
    return validate_input(suite, "suite")


def validate_mirror(mirror: str) -> str:
    """Validate mirror URL — must be http:// or https://.

    We intentionally allow http here because many Debian mirrors
    (including the default) use plain HTTP for package downloads.
    APT verifies package integrity via GPG signatures, not TLS.
    """
    if not mirror:
        raise ValidationError("mirror must not be empty")
    if not (mirror.startswith("http://") or mirror.startswith("https://")):
        raise ValidationError(f"mirror must use http:// or https://: {mirror!r}")
    return mirror


def _validate_glob(pattern: str) -> str:
    """Validate a glob pattern — rejects recursive ``**`` and unsafe characters."""
    if "**" in pattern:
        raise ValidationError(f"Recursive glob pattern '**' is not allowed: {pattern!r}")
    if not _SAFE_GLOB_RE.match(pattern):
        raise ValidationError(f"Unsafe glob pattern: {pattern!r}")
    return pattern


def _validate_chroot_path_for_removal(chroot_dir: Path) -> None:
    """Verify chroot path is deep enough to be safe for rm -rf."""
    resolved = chroot_dir.resolve()
    if str(resolved) in ("/", "\\"):
        raise ValidationError("Refusing to rm -rf filesystem root")
    depth = len(resolved.parts) - 1
    if depth < _MIN_CHROOT_DEPTH:
        raise ValidationError(
            f"Refusing to rm -rf {resolved}: path depth {depth} < "
            f"minimum {_MIN_CHROOT_DEPTH}. Chroot paths must be at least "
            f"{_MIN_CHROOT_DEPTH} levels deep (e.g. /tmp/myproject/chroot)"
        )


# ---------------------------------------------------------------------------
# Mount management
# ---------------------------------------------------------------------------


def _is_mounted(path: Path) -> bool:
    """Check whether *path* is still an active mount point."""
    result = run_cmd(
        ["mountpoint", "-q", str(path)],
        check=False,
        capture=True,
    )
    return result.returncode == 0


def _mount_filesystems(chroot_dir: Path) -> list[Path]:
    """Mount /proc, /sys, /dev inside the chroot.

    Returns the list of mounted paths (in mount order) for later cleanup.
    """
    mounted: list[Path] = []
    for fs_type, source, target in CHROOT_MOUNT_POINTS:
        mount_path = chroot_dir / target.lstrip("/")
        mount_path.mkdir(parents=True, exist_ok=True)
        log.info("Mounting %s at %s", fs_type, mount_path)
        run_cmd(["sudo", "mount", "-t", fs_type, source, str(mount_path)])
        mounted.append(mount_path)
    return mounted


def _unmount_filesystems(mounted: list[Path]) -> None:
    """Unmount filesystems in reverse order.

    Tries standard ``umount`` first; falls back to lazy ``umount -l``
    only when the standard call fails.  Best-effort — logs failures.
    """
    for mount_path in reversed(mounted):
        log.info("Unmounting %s", mount_path)
        result = run_cmd(
            ["sudo", "umount", str(mount_path)],
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            continue
        log.warning(
            "Standard unmount failed for %s, trying lazy unmount: %s",
            mount_path,
            result.stderr.strip() if result.stderr else "unknown error",
        )
        result = run_cmd(
            ["sudo", "umount", "-l", str(mount_path)],
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            log.warning(
                "Lazy unmount also failed for %s: %s",
                mount_path,
                result.stderr.strip() if result.stderr else "unknown error",
            )


@contextlib.contextmanager
def managed_mounts(chroot_dir: Path) -> Generator[list[Path], None, None]:
    """Context manager that mounts and guarantees cleanup of chroot filesystems."""
    mounted: list[Path] = []
    try:
        mounted = _mount_filesystems(chroot_dir)
        yield mounted
    finally:
        _unmount_filesystems(mounted)


# ---------------------------------------------------------------------------
# Chroot environment setup
# ---------------------------------------------------------------------------


def create_chroot(
    chroot_dir: Path,
    *,
    suite: str = DEFAULT_SUITE,
    mirror: str = DEFAULT_MIRROR,
) -> Path:
    """Create a minimal chroot environment using debootstrap.

    Parameters
    ----------
    chroot_dir:
        Directory where the chroot will be created. Must not already exist
        as a populated chroot (safety check).
    suite:
        Debian/Ubuntu release codename (e.g. ``bookworm``, ``jammy``).
    mirror:
        Package mirror URL.

    Returns
    -------
    Path
        The chroot directory.
    """
    validate_suite(suite)
    validate_mirror(mirror)

    chroot_dir = chroot_dir.resolve()
    chroot_dir.mkdir(parents=True, exist_ok=True)

    log.info("Creating chroot at %s (suite=%s, mirror=%s)", chroot_dir, suite, mirror)
    run_cmd(
        [
            "sudo",
            "debootstrap",
            "--variant=minbase",
            suite,
            str(chroot_dir),
            mirror,
        ]
    )
    log.info("Chroot created successfully at %s", chroot_dir)
    return chroot_dir


def install_build_deps(chroot_dir: Path) -> None:
    """Install kernel build dependencies inside the chroot."""
    chroot_dir = chroot_dir.resolve()
    packages = BUILD_DEPS + CHROOT_EXTRA_PACKAGES

    log.info("Installing build dependencies in chroot: %s", ", ".join(packages))
    run_cmd(
        [
            "sudo",
            "chroot",
            str(chroot_dir),
            "apt-get",
            "update",
            "-qq",
        ]
    )
    run_cmd(
        [
            "sudo",
            "chroot",
            str(chroot_dir),
            "apt-get",
            "install",
            "-y",
            "-qq",
            *packages,
        ]
    )
    log.info("Build dependencies installed")


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------


def copy_source_into_chroot(
    source_dir: Path,
    chroot_dir: Path,
) -> Path:
    """Copy kernel source tree into the chroot's ``/build`` directory.

    Returns the path *inside* the chroot filesystem (host-relative).
    """
    source_dir = source_dir.resolve()
    chroot_dir = chroot_dir.resolve()

    if not source_dir.is_dir():
        raise ValidationError(f"Source directory does not exist: {source_dir}")

    build_dir = chroot_dir / "build"
    dest = build_dir / source_dir.name
    if dest.exists():
        log.info("Source already present at %s — removing for fresh copy", dest)
        shutil.rmtree(dest)

    build_dir.mkdir(parents=True, exist_ok=True)
    log.info("Copying kernel source %s -> %s", source_dir, dest)
    shutil.copytree(source_dir, dest, symlinks=True)
    log.info("Kernel source copied into chroot")
    return dest


# ---------------------------------------------------------------------------
# Build execution
# ---------------------------------------------------------------------------


def run_chroot_build(
    chroot_dir: Path,
    chroot_source_path: Path,
    *,
    jobs: int | None = None,
) -> None:
    """Execute kernel compilation inside the chroot.

    Parameters
    ----------
    chroot_dir:
        Root of the chroot filesystem.
    chroot_source_path:
        Host-relative path to the source tree inside the chroot
        (e.g. ``/path/to/chroot/build/linux-6.8.1``).
    jobs:
        Number of parallel make jobs. Auto-detected if ``None``.
    """
    from myproject.kernel_builder import compute_optimal_jobs

    chroot_dir = chroot_dir.resolve()
    chroot_source_path = chroot_source_path.resolve()

    # Convert host-absolute path to chroot-relative path
    try:
        inner_path = "/" / chroot_source_path.relative_to(chroot_dir)
    except ValueError:
        raise ValidationError(
            f"Source path {chroot_source_path} is not inside chroot {chroot_dir}"
        ) from None

    j = jobs if jobs is not None else compute_optimal_jobs()

    log.info("Running kernel build in chroot (jobs=%d, source=%s)", j, inner_path)
    run_cmd(
        [
            "sudo",
            "chroot",
            str(chroot_dir),
            "make",
            "-C",
            str(inner_path),
            f"-j{j}",
            "bindeb-pkg",
        ]
    )
    log.info("Chroot build completed")


# ---------------------------------------------------------------------------
# Artifact extraction
# ---------------------------------------------------------------------------


def extract_artifacts(
    chroot_dir: Path,
    output_dir: Path,
) -> list[Path]:
    """Copy ``.deb`` build artifacts out of the chroot.

    Looks in ``<chroot>/build/`` for ``.deb`` files produced by
    ``make bindeb-pkg``.

    Returns list of copied artifact paths in *output_dir*.
    """
    chroot_dir = chroot_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    build_dir = chroot_dir / "build"
    if not build_dir.is_dir():
        raise BuildError(f"Build directory not found in chroot: {build_dir}")

    pattern = _validate_glob("*.deb")
    debs = sorted(build_dir.glob(pattern))
    if not debs:
        raise BuildError(f"No .deb artifacts found in {build_dir}")

    copied: list[Path] = []
    for deb in debs:
        dest = output_dir / deb.name
        shutil.copy2(deb, dest)
        log.info("Extracted artifact: %s", dest)
        copied.append(dest)

    log.info("Extracted %d artifact(s) to %s", len(copied), output_dir)
    return copied


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def teardown_chroot(chroot_dir: Path, *, remove: bool = False) -> None:
    """Teardown chroot — unmount any lingering mounts and optionally remove.

    Parameters
    ----------
    remove:
        If True, recursively delete the chroot directory after unmounting.
    """
    chroot_dir = chroot_dir.resolve()

    # Build list of expected mount points and unmount any that are still active
    expected_mounts: list[Path] = []
    for _fs_type, _source, target in CHROOT_MOUNT_POINTS:
        mount_path = chroot_dir / target.lstrip("/")
        if mount_path.exists():
            expected_mounts.append(mount_path)

    if expected_mounts:
        log.info("Cleaning up lingering mount points")
        _unmount_filesystems(expected_mounts)

    if remove:
        # SECURITY: Validate path depth to prevent catastrophic rm -rf
        _validate_chroot_path_for_removal(chroot_dir)

        # SECURITY: Verify all mount points are actually unmounted before rm -rf
        for _fs_type2, _source2, target2 in CHROOT_MOUNT_POINTS:
            mount_path = chroot_dir / target2.lstrip("/")
            if mount_path.exists() and _is_mounted(mount_path):
                raise BuildError(
                    f"Mount point {mount_path} is still active after unmount. "
                    f"Refusing rm -rf to protect host filesystems."
                )

        if chroot_dir.exists():
            log.info("Removing chroot directory: %s", chroot_dir)
            run_cmd(["sudo", "rm", "-rf", str(chroot_dir)])
            log.info("Chroot removed")
    else:
        log.info("Chroot preserved at %s", chroot_dir)


# ---------------------------------------------------------------------------
# High-level orchestrator
# ---------------------------------------------------------------------------


def chroot_kernel_build(
    source_dir: Path,
    output_dir: Path,
    *,
    chroot_dir: Path | None = None,
    suite: str = DEFAULT_SUITE,
    mirror: str = DEFAULT_MIRROR,
    jobs: int | None = None,
    cleanup: bool = True,
) -> list[Path]:
    """End-to-end chroot kernel build.

    1. Create chroot via debootstrap
    2. Mount /proc, /sys, /dev
    3. Install build dependencies
    4. Copy kernel source into chroot
    5. Compile kernel (make bindeb-pkg)
    6. Extract .deb artifacts
    7. Tear down chroot

    Parameters
    ----------
    source_dir:
        Path to the kernel source tree on the host.
    output_dir:
        Where to copy the resulting ``.deb`` packages.
    chroot_dir:
        Where to create the chroot. Defaults to ``output_dir / ".chroot"``.
    suite:
        Debian/Ubuntu release codename.
    mirror:
        Package mirror URL.
    jobs:
        Parallel make jobs. Auto-detected if ``None``.
    cleanup:
        Whether to remove the chroot after build.

    Returns
    -------
    list[Path]
        Paths to the extracted ``.deb`` artifacts.
    """
    if chroot_dir is None:
        chroot_dir = output_dir / ".chroot"

    try:
        create_chroot(chroot_dir, suite=suite, mirror=mirror)

        with managed_mounts(chroot_dir):
            install_build_deps(chroot_dir)
            chroot_source = copy_source_into_chroot(source_dir, chroot_dir)
            run_chroot_build(chroot_dir, chroot_source, jobs=jobs)
            artifacts = extract_artifacts(chroot_dir, output_dir)

        return artifacts
    finally:
        teardown_chroot(chroot_dir, remove=cleanup)
