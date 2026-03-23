"""UEFI Secure Boot automation for Manjaro/Arch Linux.

Automates MOK (Machine Owner Key) generation, kernel and DKMS module
signing, MOK enrollment, and pacman hook installation for persistent
Secure Boot support across kernel updates.

Integrates with :mod:`myproject.kernel_builder` for shared subprocess
helpers and validation.
"""

from __future__ import annotations

import logging
import shutil
import stat
from pathlib import Path

from myproject.kernel_builder import BuildError, run_cmd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_TOOLS: tuple[str, ...] = ("sbsign", "mokutil", "openssl")

MOK_KEY_FILENAME: str = "MOK.key"
MOK_CERT_FILENAME: str = "MOK.crt"

BOOT_DIR: Path = Path("/boot")
LIB_MODULES_DIR: Path = Path("/lib/modules")

PACMAN_HOOK_DIR: Path = Path("/etc/pacman.d/hooks")
PACMAN_HOOK_NAME: str = "99-secureboot.hook"

PACMAN_HOOK_TEMPLATE: str = """\
[Trigger]
Operation = Install
Operation = Upgrade
Type = Path
Target = usr/lib/modules/*/vmlinuz
Target = boot/vmlinuz-*

[Action]
Description = Signing kernels for Secure Boot...
When = PostTransaction
Exec = /usr/bin/sbsign --key {key} --cert {cert} --output %f %f
Depends = sbsigntools
"""


# ---------------------------------------------------------------------------
# Tool availability
# ---------------------------------------------------------------------------


def ensure_tools_installed() -> None:
    """Verify that sbsign, mokutil, and openssl are on PATH.

    Raises:
        BuildError: If any required tool is missing.
    """
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        raise BuildError(
            f"Required tools not found: {', '.join(missing)}. "
            f"Install with: sudo pacman -S sbsigntools mokutil openssl"
        )
    log.info("All required tools present: %s", ", ".join(REQUIRED_TOOLS))


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_mok_keys(key_dir: str | Path) -> tuple[Path, Path]:
    """Generate an RSA MOK key pair if not already present.

    Args:
        key_dir: Directory to store MOK.key and MOK.crt.

    Returns:
        Tuple of (key_path, cert_path).

    Raises:
        BuildError: If openssl fails.
    """
    key_dir = Path(key_dir).resolve()
    key_dir.mkdir(parents=True, exist_ok=True)

    key_path = key_dir / MOK_KEY_FILENAME
    cert_path = key_dir / MOK_CERT_FILENAME

    if key_path.exists() and cert_path.exists():
        log.info("MOK key pair already exists in %s", key_dir)
        _enforce_key_permissions(key_path, cert_path)
        return key_path, cert_path

    log.info("Generating MOK key pair in %s ...", key_dir)
    run_cmd(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "3650",
            "-subj",
            "/CN=Secure Boot MOK Signing Key",
        ]
    )

    _enforce_key_permissions(key_path, cert_path)
    log.info("MOK key pair generated successfully")
    return key_path, cert_path


def _enforce_key_permissions(key_path: Path, cert_path: Path) -> None:
    """Set private key to 0o600 and certificate to 0o644."""
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    cert_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o644
    log.debug("Permissions: %s=0600, %s=0644", key_path, cert_path)


# ---------------------------------------------------------------------------
# Kernel signing
# ---------------------------------------------------------------------------


def sign_kernel(kernel_path: str | Path, key_path: str | Path, cert_path: str | Path) -> None:
    """Sign a single kernel image with sbsign.

    Args:
        kernel_path: Path to vmlinuz image.
        key_path: Path to MOK private key.
        cert_path: Path to MOK certificate.

    Raises:
        FileNotFoundError: If any input file is missing.
        BuildError: If sbsign fails.
    """
    kernel_path = Path(kernel_path).resolve()
    key_path = Path(key_path).resolve()
    cert_path = Path(cert_path).resolve()

    for path, label in [
        (kernel_path, "kernel"),
        (key_path, "private key"),
        (cert_path, "certificate"),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    log.info("Signing kernel: %s", kernel_path)
    run_cmd(
        [
            "sbsign",
            "--key",
            str(key_path),
            "--cert",
            str(cert_path),
            "--output",
            str(kernel_path),
            str(kernel_path),
        ]
    )
    log.info("Signed: %s", kernel_path)


def sign_all_kernels(key_dir: str | Path) -> list[Path]:
    """Find and sign all /boot/vmlinuz-* kernels.

    Args:
        key_dir: Directory containing MOK.key and MOK.crt.

    Returns:
        List of signed kernel paths.
    """
    key_dir = Path(key_dir).resolve()
    key_path = key_dir / MOK_KEY_FILENAME
    cert_path = key_dir / MOK_CERT_FILENAME

    kernels = sorted(BOOT_DIR.glob("vmlinuz-*"))
    if not kernels:
        log.warning("No kernels found in %s", BOOT_DIR)
        return []

    signed: list[Path] = []
    for kernel in kernels:
        sign_kernel(kernel, key_path, cert_path)
        signed.append(kernel)

    log.info("Signed %d kernel(s)", len(signed))
    return signed


# ---------------------------------------------------------------------------
# DKMS module signing
# ---------------------------------------------------------------------------


def sign_dkms_modules(key_dir: str | Path) -> list[Path]:
    """Find and sign .ko files in /lib/modules/.

    Args:
        key_dir: Directory containing MOK.key and MOK.crt.

    Returns:
        List of signed module paths.
    """
    key_dir = Path(key_dir).resolve()
    key_path = key_dir / MOK_KEY_FILENAME
    cert_path = key_dir / MOK_CERT_FILENAME

    for path, label in [(key_path, "private key"), (cert_path, "certificate")]:
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    modules = sorted(LIB_MODULES_DIR.rglob("*.ko"))
    if not modules:
        log.warning("No .ko modules found in %s", LIB_MODULES_DIR)
        return []

    signed: list[Path] = []
    for mod in modules:
        mod_resolved = mod.resolve()
        log.info("Signing module: %s", mod_resolved)
        run_cmd(
            [
                "sbsign",
                "--key",
                str(key_path),
                "--cert",
                str(cert_path),
                "--output",
                str(mod_resolved),
                str(mod_resolved),
            ]
        )
        signed.append(mod_resolved)

    log.info("Signed %d module(s)", len(signed))
    return signed


# ---------------------------------------------------------------------------
# MOK enrollment
# ---------------------------------------------------------------------------


def is_mok_enrolled(cert_path: str | Path) -> bool:
    """Check if a MOK certificate is already enrolled.

    Args:
        cert_path: Path to the MOK certificate.

    Returns:
        True if the certificate is enrolled, False otherwise.
    """
    cert_path = Path(cert_path).resolve()
    if not cert_path.exists():
        raise FileNotFoundError(f"Certificate not found: {cert_path}")

    result = run_cmd(
        ["mokutil", "--test-key", str(cert_path)],
        check=False,
        capture=True,
    )
    # mokutil --test-key prints "is already enrolled" when the key is in the MOK list
    enrolled = "is already enrolled" in result.stdout
    log.debug("MOK enrolled check for %s: %s", cert_path, enrolled)
    return enrolled


def enroll_mok(cert_path: str | Path) -> None:
    """Enroll a MOK certificate via mokutil --import.

    This will prompt the user for a one-time password that must be
    entered on next reboot in the MOK Manager EFI screen.

    Args:
        cert_path: Path to the MOK certificate to enroll.

    Raises:
        FileNotFoundError: If the certificate does not exist.
        BuildError: If enrollment fails.
    """
    cert_path = Path(cert_path).resolve()
    if not cert_path.exists():
        raise FileNotFoundError(f"Certificate not found: {cert_path}")

    if is_mok_enrolled(cert_path):
        log.info("MOK already enrolled: %s", cert_path)
        return

    log.info("Enrolling MOK certificate (password prompt follows) ...")
    run_cmd(["mokutil", "--import", str(cert_path)])
    log.info("MOK enrollment queued — reboot and enter the password in MOK Manager to complete.")


# ---------------------------------------------------------------------------
# Pacman hook
# ---------------------------------------------------------------------------


def install_pacman_hook(key_dir: str | Path) -> Path:
    """Write a pacman hook that auto-signs kernels after updates.

    Args:
        key_dir: Directory containing MOK.key and MOK.crt.

    Returns:
        Path to the installed hook file.
    """
    key_dir = Path(key_dir).resolve()
    key_path = key_dir / MOK_KEY_FILENAME
    cert_path = key_dir / MOK_CERT_FILENAME

    for path, label in [(key_path, "private key"), (cert_path, "certificate")]:
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    hook_dir = PACMAN_HOOK_DIR
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hook_dir / PACMAN_HOOK_NAME

    content = PACMAN_HOOK_TEMPLATE.format(key=key_path, cert=cert_path)
    hook_path.write_text(content, encoding="utf-8")
    log.info("Pacman hook installed: %s", hook_path)
    return hook_path


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------


def check_status() -> dict[str, object]:
    """Return a dict summarising Secure Boot state.

    Keys:
        secure_boot_enabled (bool): Whether UEFI Secure Boot is on.
        keys_present (bool): Whether MOK key pair exists in default location.
        kernels_signed (list[str]): Basenames of signed kernels.
    """
    # Secure Boot state via mokutil
    sb_result = run_cmd(["mokutil", "--sb-state"], check=False, capture=True)
    sb_enabled = "SecureBoot enabled" in sb_result.stdout

    # Check default key location
    default_key_dir = Path("/var/lib/secureboot")
    keys_present = (default_key_dir / MOK_KEY_FILENAME).exists() and (
        default_key_dir / MOK_CERT_FILENAME
    ).exists()

    # Check which kernels carry a signature
    signed_kernels: list[str] = []
    for kernel in sorted(BOOT_DIR.glob("vmlinuz-*")):
        verify = run_cmd(
            ["sbverify", "--cert", str(default_key_dir / MOK_CERT_FILENAME), str(kernel)],
            check=False,
            capture=True,
        )
        if verify.returncode == 0:
            signed_kernels.append(kernel.name)

    status: dict[str, object] = {
        "secure_boot_enabled": sb_enabled,
        "keys_present": keys_present,
        "kernels_signed": signed_kernels,
    }
    log.info("Secure Boot status: %s", status)
    return status


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def setup_secureboot(key_dir: str | Path) -> dict[str, object]:
    """Full Secure Boot setup: keys → sign → enroll → hook.

    Args:
        key_dir: Directory to store/read MOK keys.

    Returns:
        Summary dict with setup results.
    """
    key_dir = Path(key_dir).resolve()
    log.info("=== Secure Boot setup starting (key_dir=%s) ===", key_dir)

    ensure_tools_installed()

    key_path, cert_path = generate_mok_keys(key_dir)
    signed_kernels = sign_all_kernels(key_dir)
    signed_modules = sign_dkms_modules(key_dir)
    enroll_mok(cert_path)
    hook_path = install_pacman_hook(key_dir)

    summary: dict[str, object] = {
        "key_dir": str(key_dir),
        "key_path": str(key_path),
        "cert_path": str(cert_path),
        "signed_kernels": [str(k) for k in signed_kernels],
        "signed_modules": [str(m) for m in signed_modules],
        "hook_installed": str(hook_path),
    }
    log.info("=== Secure Boot setup complete ===")
    log.info("Summary: %s", summary)
    return summary
