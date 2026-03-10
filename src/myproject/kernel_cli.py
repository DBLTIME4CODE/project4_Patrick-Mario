"""Linux kernel builder CLI — numerical menu interface."""

from __future__ import annotations

import logging
from pathlib import Path

from myproject.kernel_builder import (
    _sanitize_cert_configs,
    build_deb_package,
    build_kernel,
    check_flash_kernel,
    configure_kernel,
    download_kernel,
    enforce_locale,
    ensure_build_deps,
    extract_running_config,
    fetch_latest_version,
    fetch_ubuntu_source,
    generate_signing_key,
    get_running_kernel,
    install_kernel,
    numbered_menu,
    prompt_yes_no,
    run_cmd,
    setup_logging,
    sign_kernel,
    validate_input,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prompt_build_dir() -> Path:
    """Ask the user for a build directory."""
    default = Path.home() / "kernel-build"
    raw = input(f"Build directory [{default}]: ").strip()
    build_dir = Path(raw) if raw else default
    build_dir.mkdir(parents=True, exist_ok=True)
    return build_dir


def _prompt_log_preference() -> Path | None:
    """Ask whether to log build output to a file."""
    if prompt_yes_no("Redirect build output to a log file?"):
        default = Path.home() / "kernel-build" / "build.log"
        raw = input(f"Log file path [{default}]: ").strip()
        return Path(raw) if raw else default
    return None


def _should_clean(source_dir: Path) -> bool:
    """Return True if source_dir has stale build artifacts and user wants a clean build."""
    if (source_dir / ".config").exists() or (source_dir / "vmlinux").exists():
        log.info("Previous build artifacts detected in %s", source_dir)
        return prompt_yes_no("Clean stale build artifacts before reconfiguring (make mrproper)?")
    return False


def _handle_config_menu(source_dir: Path) -> None:
    """Sub-menu for kernel configuration strategy."""
    clean = _should_clean(source_dir)
    choice = numbered_menu(
        "Kernel configuration",
        [
            "Use running kernel's config (olddefconfig)",
            "Use default config (defconfig)",
            "Run menuconfig (interactive)",
        ],
    )
    if choice == 0:
        config_path = extract_running_config(source_dir)
        configure_kernel(source_dir, config_path, clean=clean)
    elif choice == 1:
        if clean:
            log.info("Cleaning stale build artifacts (make mrproper) ...")
            run_cmd(["make", "mrproper"], cwd=source_dir)
        run_cmd(["make", "defconfig"], cwd=source_dir)
        _sanitize_cert_configs(source_dir)
        run_cmd(["make", "olddefconfig"], cwd=source_dir)
    else:
        if clean:
            log.info("Cleaning stale build artifacts (make mrproper) ...")
            run_cmd(["make", "mrproper"], cwd=source_dir)
        run_cmd(["make", "menuconfig"], cwd=source_dir)
        _sanitize_cert_configs(source_dir)
        run_cmd(["make", "olddefconfig"], cwd=source_dir)


def _handle_signing(source_dir: Path) -> None:
    """Optional kernel signing sub-flow."""
    if not prompt_yes_no("Sign the kernel?"):
        return

    key_choice = numbered_menu(
        "Signing key",
        [
            "Generate a new signing key pair",
            "Use existing key and certificate",
        ],
    )

    if key_choice == 0:
        key_path, cert_path = generate_signing_key(source_dir.parent)
    else:
        key_input = input("Path to private key (.pem): ").strip()
        cert_input = input("Path to certificate (.pem): ").strip()
        key_path = Path(key_input)
        cert_path = Path(cert_input)

    sign_kernel(source_dir, key_path, cert_path)


def _handle_build_output(
    source_dir: Path,
    build_dir: Path,
    log_file: Path | None,
) -> None:
    """Sub-menu: compile or generate .deb."""
    choice = numbered_menu(
        "Build output",
        [
            "Compile kernel only (make)",
            "Generate .deb packages (make bindeb-pkg)",
        ],
    )

    if choice == 0:
        build_kernel(source_dir, log_file=log_file)
        if prompt_yes_no("Install the compiled kernel now?"):
            install_kernel(source_dir)
    else:
        build_deb_package(source_dir, log_file=log_file)
        log.info(".deb packages are in %s", build_dir)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the kernel builder CLI."""
    try:
        _main_inner()
    except EOFError:
        raise SystemExit("EOF received \u2014 aborting") from None
    except KeyboardInterrupt:
        raise SystemExit(
            "\nInterrupted \u2014 partial build artifacts may remain in the build directory"
        ) from None


def _main_inner() -> None:
    """Actual CLI logic — main() wraps this for EOFError."""
    setup_logging()
    enforce_locale()
    check_flash_kernel()

    menu_options = [
        "Build mainline kernel (specific version)",
        "Build latest stable kernel from kernel.org",
        "Rebuild running kernel from source",
        "Build Ubuntu-patched kernel",
        "Exit",
    ]

    choice = numbered_menu("Linux Kernel Builder", menu_options)

    if choice == 4:
        print("Goodbye.")
        return

    build_dir = _prompt_build_dir()
    log_file = _prompt_log_preference()

    ensure_build_deps()

    source_dir: Path

    if choice == 0:
        # Specific mainline version
        version = input("Kernel version to build (e.g. 6.8.1): ").strip()
        validate_input(version, "kernel version")
        source_dir = download_kernel(version, build_dir)
        _handle_config_menu(source_dir)

    elif choice == 1:
        # Latest stable
        version = fetch_latest_version()
        print(f"Latest stable kernel: {version}")
        if not prompt_yes_no(f"Build kernel {version}?"):
            return
        source_dir = download_kernel(version, build_dir)
        _handle_config_menu(source_dir)

    elif choice == 2:
        # Rebuild running kernel
        version = get_running_kernel()
        base = version.split("-")[0]
        source_dir = download_kernel(base, build_dir)
        clean = _should_clean(source_dir)
        config_path = extract_running_config(source_dir)
        configure_kernel(source_dir, config_path, clean=clean)

    elif choice == 3:
        # Ubuntu-patched kernel
        source_dir = fetch_ubuntu_source(build_dir)
        clean = _should_clean(source_dir)
        config_path = extract_running_config(source_dir)
        configure_kernel(source_dir, config_path, clean=clean)

    else:
        return

    _handle_build_output(source_dir, build_dir, log_file)
    _handle_signing(source_dir)

    log.info("Done!")


if __name__ == "__main__":
    main()
