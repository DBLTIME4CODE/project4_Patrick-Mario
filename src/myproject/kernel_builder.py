"""Linux kernel builder — download, configure, compile, and install kernels.

Core engine module providing validation, downloads, build, install, and signing
for mainline, running, and Ubuntu-patched kernels on Debian/Ubuntu systems.
All user input is validated against a strict whitelist.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import lzma
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_INPUT_LENGTH: int = 256
MAX_RETRIES: int = 3

SAFE_INPUT_RE: re.Pattern[str] = re.compile(r"^[0-9a-zA-Z.\-]+$")
SAFE_KERNEL_VERSION_RE: re.Pattern[str] = re.compile(r"^[0-9a-zA-Z.\-+_]+$")

BUILD_DEPS: list[str] = [
    "build-essential",
    "libncurses-dev",
    "bison",
    "flex",
    "libssl-dev",
    "libelf-dev",
    "bc",
    "dwarves",
    "wget",
    "xz-utils",
    "cpio",
    "rsync",
    "gnupg",
    "fakeroot",
    "dpkg-dev",
    "debhelper",
]

KERNEL_ORG_BASE: str = "https://cdn.kernel.org/pub/linux/kernel"
KERNEL_ORG_RELEASES: str = "https://www.kernel.org/releases.json"

ALLOWED_DOWNLOAD_DOMAINS: frozenset[str] = frozenset(
    {
        "cdn.kernel.org",
        "www.kernel.org",
        "kernel.org",
    }
)

# kernel.org release signing keys
KERNEL_ORG_SIGNING_KEYS: tuple[str, ...] = (
    "647F28654894E3BD457199BE38DBBDC86092693E",  # Greg Kroah-Hartman
    "ABAF11C65A2970B130ABE3C479BE3E4300411886",  # Linus Torvalds
)
KERNEL_ORG_KEYSERVER: str = "hkps://keys.openpgp.org"

_gpg_keys_imported: bool = False


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when user input fails validation."""


class BuildError(RuntimeError):
    """Raised when a kernel build fails after all retries."""


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def validate_input(value: str, label: str = "input") -> str:
    """Validate *value* contains only ``[0-9a-zA-Z.-]``."""
    if not value:
        raise ValidationError(f"{label} must not be empty")
    if "\x00" in value:
        raise ValidationError(f"{label} contains null bytes")
    if len(value) > MAX_INPUT_LENGTH:
        raise ValidationError(f"{label} exceeds maximum length of {MAX_INPUT_LENGTH}")
    if not SAFE_INPUT_RE.match(value):
        raise ValidationError(
            f"{label} contains invalid characters (allowed: 0-9 a-z A-Z . -): {value!r}"
        )
    return value


def validate_kernel_version(value: str, label: str = "kernel version") -> str:
    """Validate a kernel version from ``uname -r``.

    Allows ``[0-9a-zA-Z.\\-+_]`` — slightly relaxed compared to
    :func:`validate_input` because real kernel versions can contain
    ``+`` (custom builds) and ``_`` (some distro suffixes).
    """
    if not value:
        raise ValidationError(f"{label} must not be empty")
    if "\x00" in value:
        raise ValidationError(f"{label} contains null bytes")
    if len(value) > MAX_INPUT_LENGTH:
        raise ValidationError(f"{label} exceeds maximum length of {MAX_INPUT_LENGTH}")
    if not SAFE_KERNEL_VERSION_RE.match(value):
        raise ValidationError(
            f"{label} contains invalid characters (allowed: 0-9 a-z A-Z . - + _): {value!r}"
        )
    return value


def validate_url_domain(url: str) -> str:
    """Verify *url* targets an allowed download domain."""
    if not url.startswith("https://"):
        raise ValidationError(f"URL must use HTTPS: {url!r}")
    without_scheme = url[len("https://") :]
    domain = without_scheme.split("/", 1)[0].split(":", 1)[0]
    if domain not in ALLOWED_DOWNLOAD_DOMAINS:
        raise ValidationError(
            f"Domain {domain!r} is not in the allowed list: {sorted(ALLOWED_DOWNLOAD_DOMAINS)}"
        )
    return url


# ---------------------------------------------------------------------------
# Locale enforcement
# ---------------------------------------------------------------------------


def enforce_locale() -> None:
    """Set ``LANG`` and ``LC_ALL`` to ``en_US.UTF-8``."""
    for var in ("LANG", "LC_ALL"):
        os.environ[var] = "en_US.UTF-8"
    log.info("Locale set to en_US.UTF-8")


# ---------------------------------------------------------------------------
# System helpers
# ---------------------------------------------------------------------------


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command — never with ``shell=True``."""
    merged_env: dict[str, str] | None = None
    if env:
        merged_env = {**os.environ, **env}
    log.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
        env=merged_env,
    )


def _run_streaming(
    cmd: list[str],
    *,
    cwd: Path,
    log_file: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Run *cmd* with line-buffered streaming output."""
    log.debug("Streaming: %s (cwd=%s)", " ".join(cmd), cwd)
    merged_env: dict[str, str] | None = None
    if env:
        merged_env = {**os.environ, **env}
    fh = None
    try:
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = open(log_file, "a")  # noqa: SIM115
        with subprocess.Popen(
            cmd,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            env=merged_env,
        ) as proc:
            assert proc.stdout is not None
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                if fh:
                    fh.write(line)
                else:
                    sys.stdout.write(line)
                    sys.stdout.flush()
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
    finally:
        if fh:
            fh.close()


def get_running_kernel() -> str:
    """Return the running kernel version (``uname -r``)."""
    result = run_cmd(["uname", "-r"], capture=True)
    version = result.stdout.strip()
    log.info("Running kernel: %s", version)
    return version


def check_flash_kernel() -> bool:
    """Return ``True`` if ``flash-kernel`` is installed."""
    result = run_cmd(
        ["dpkg", "-s", "flash-kernel"],
        check=False,
        capture=True,
    )
    installed = result.returncode == 0
    if installed:
        log.info("flash-kernel is installed")
    else:
        log.warning("flash-kernel is NOT installed — may be needed for ARM/embedded")
    return installed


def install_packages(packages: list[str]) -> None:
    """Install system packages via ``apt-get``."""
    log.info("Installing packages: %s", ", ".join(packages))
    run_cmd(["sudo", "apt-get", "update", "-qq"])
    run_cmd(["sudo", "apt-get", "install", "-y", "-qq", *packages])


def ensure_build_deps() -> None:
    """Install all required build dependencies."""
    install_packages(BUILD_DEPS)


def has_ccache() -> bool:
    """Return ``True`` if ccache is on PATH."""
    return shutil.which("ccache") is not None


# ---------------------------------------------------------------------------
# Parallelism / resource detection
# ---------------------------------------------------------------------------


def _cpu_count() -> int:
    """Return usable CPU count, >= 1."""
    return max(os.cpu_count() or 1, 1)


def _available_ram_gb() -> float:
    """Return available RAM in GiB via ``/proc/meminfo``."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 4.0


def compute_optimal_jobs() -> int:
    """``min(cpus, available_ram_gb * 2)`` to prevent OOM."""
    cpus = _cpu_count()
    ram_jobs = max(int(_available_ram_gb() * 2), 1)
    jobs = min(cpus, ram_jobs)
    log.info(
        "Optimal jobs: %d (cpus=%d, ram-based=%d)",
        jobs,
        cpus,
        ram_jobs,
    )
    return jobs


# ---------------------------------------------------------------------------
# Config extraction
# ---------------------------------------------------------------------------


def extract_running_config(dest_dir: Path) -> Path:
    """Copy the running kernel config into *dest_dir*/.config."""
    version = get_running_kernel()
    validate_kernel_version(version, "kernel version")
    boot_config = Path(f"/boot/config-{version}")
    proc_config = Path("/proc/config.gz")
    target = dest_dir / ".config"

    if boot_config.exists():
        shutil.copy2(boot_config, target)
        log.info("Copied config from %s", boot_config)
    elif proc_config.exists():
        with gzip.open(proc_config, "rb") as gz:
            with open(target, "wb") as out:
                shutil.copyfileobj(gz, out)
        log.info("Extracted config from %s", proc_config)
    else:
        raise FileNotFoundError(f"No kernel config found at {boot_config} or {proc_config}")
    return target


# ---------------------------------------------------------------------------
# Download — security-hardened
# ---------------------------------------------------------------------------


def _normalize_kernel_version(version: str) -> str:
    """Strip trailing '.0' — kernel.org publishes '6.5' not '6.5.0'."""
    if version.endswith(".0") and version.count(".") == 2:
        return version[:-2]
    return version


def _kernel_url(version: str) -> str:
    """Build kernel.org download URL for *version*."""
    major = version.split(".")[0]
    normalized = _normalize_kernel_version(version)
    return f"{KERNEL_ORG_BASE}/v{major}.x/linux-{normalized}.tar.xz"


def _kernel_sig_url(version: str) -> str:
    """Build kernel.org GPG signature URL for *version*."""
    major = version.split(".")[0]
    normalized = _normalize_kernel_version(version)
    return f"{KERNEL_ORG_BASE}/v{major}.x/linux-{normalized}.tar.sign"


def fetch_latest_version() -> str:
    """Fetch the latest stable version from kernel.org."""
    url = KERNEL_ORG_RELEASES
    validate_url_domain(url)
    log.info("Fetching latest kernel version from %s", url)
    req = Request(
        url,
        headers={"User-Agent": "myproject-kernel-builder"},
    )
    with urlopen(req, timeout=30) as resp:  # noqa: S310
        data = json.loads(resp.read().decode())
    version: str = data["latest_stable"]["version"]
    validate_input(version, "latest kernel version")
    log.info("Latest stable kernel: %s", version)
    return version


def verify_checksum(
    file_path: Path,
    expected_sha256: str,
) -> None:
    """Verify SHA-256 checksum of *file_path*."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    actual = sha.hexdigest()
    if actual != expected_sha256:
        raise ValidationError(
            f"SHA-256 mismatch for {file_path.name}: expected {expected_sha256}, got {actual}"
        )
    log.info("SHA-256 verified for %s", file_path.name)


def _ensure_kernel_org_keys() -> bool:
    """Import kernel.org GPG signing keys if not already imported this session."""
    global _gpg_keys_imported  # noqa: PLW0603
    if _gpg_keys_imported:
        return True
    log.info("Importing kernel.org signing keys from %s", KERNEL_ORG_KEYSERVER)
    result = run_cmd(
        [
            "gpg",
            "--keyserver",
            KERNEL_ORG_KEYSERVER,
            "--keyserver-options",
            "timeout=10",
            "--recv-keys",
            *KERNEL_ORG_SIGNING_KEYS,
        ],
        check=False,
        capture=True,
    )
    if result.returncode == 0:
        _gpg_keys_imported = True
        log.info("Kernel.org signing keys imported successfully")
        return True
    log.warning(
        "Could not import kernel.org signing keys (keyserver may be down): %s",
        result.stderr.strip() if result.stderr else "unknown error",
    )
    return False


def verify_gpg_signature(
    file_path: Path,
    sig_path: Path,
) -> bool:
    """Verify GPG signature. Returns True if valid."""
    result = run_cmd(
        ["gpg", "--verify", str(sig_path), str(file_path)],
        check=False,
        capture=True,
    )
    if result.returncode == 0:
        log.info("GPG signature verified for %s", file_path.name)
        return True
    log.warning(
        "GPG verification failed for %s: %s",
        file_path.name,
        result.stderr.strip() if result.stderr else "unknown",
    )
    return False


def safe_extract_tarball(tarball: Path, dest: Path) -> None:
    """Extract tarball with path-traversal prevention."""
    dest_resolved = dest.resolve()
    with tarfile.open(tarball) as tf:
        for member in tf.getmembers():
            member_path = (dest / member.name).resolve()
            try:
                member_path.relative_to(dest_resolved)
            except ValueError:
                raise ValidationError(
                    f"Path traversal detected in tarball member: {member.name!r}"
                ) from None
            if member.issym() or member.islnk():
                link_target = (dest / os.path.dirname(member.name) / member.linkname).resolve()
                try:
                    link_target.relative_to(dest_resolved)
                except ValueError:
                    raise ValidationError(
                        f"Symlink traversal in tarball: {member.name!r} -> {member.linkname!r}"
                    ) from None
        if sys.version_info >= (3, 12):
            tf.extractall(dest, filter="data")  # noqa: S202
        else:
            tf.extractall(dest)  # noqa: S202
    log.info("Safely extracted %s", tarball.name)


def download_kernel(version: str, dest: Path) -> Path:
    """Download and extract a mainline kernel tarball."""
    validate_input(version, "kernel version")
    dest.mkdir(parents=True, exist_ok=True)

    url = _kernel_url(version)
    validate_url_domain(url)
    normalized = _normalize_kernel_version(version)
    tarball = dest / f"linux-{normalized}.tar.xz"

    log.info("Downloading %s", url)
    run_cmd(
        [
            "wget",
            "-q",
            "--show-progress",
            "--continue",
            "-O",
            str(tarball),
            url,
        ]
    )

    # GPG signature verification (best-effort)
    sig_url = _kernel_sig_url(version)
    sig_path = dest / f"linux-{normalized}.tar.sign"
    sig_result = run_cmd(
        [
            "wget",
            "-q",
            "--continue",
            "-O",
            str(sig_path),
            sig_url,
        ],
        check=False,
        capture=True,
    )
    if sig_result.returncode == 0 and sig_path.exists():
        # kernel.org signs the uncompressed .tar, not .tar.xz
        _ensure_kernel_org_keys()
        tar_path = tarball.with_suffix("")  # .tar.xz → .tar
        try:
            with lzma.open(tarball, "rb") as xz_f, open(tar_path, "wb") as tar_f:
                shutil.copyfileobj(xz_f, tar_f)
            if not verify_gpg_signature(tar_path, sig_path):
                log.warning("GPG verification failed — continuing.")
        finally:
            tar_path.unlink(missing_ok=True)
    else:
        log.info("No GPG signature available — skipping")

    log.info("Extracting %s", tarball.name)
    safe_extract_tarball(tarball, dest)

    source_dir = dest / f"linux-{normalized}"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Expected source directory not found: {source_dir}")
    return source_dir


def fetch_ubuntu_source(dest: Path) -> Path:
    """Fetch Ubuntu-patched kernel source."""
    dest.mkdir(parents=True, exist_ok=True)
    version = get_running_kernel()
    validate_kernel_version(version, "kernel version")

    log.info("Fetching Ubuntu kernel source for %s", version)
    run_cmd(
        [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "-qq",
            "dpkg-dev",
        ]
    )
    run_cmd(
        ["apt-get", "source", f"linux-image-{version}"],
        cwd=dest,
    )

    for child in sorted(dest.iterdir()):
        if child.is_dir() and child.name.startswith("linux"):
            log.info("Ubuntu source at %s", child)
            return child

    raise FileNotFoundError("Could not locate extracted Ubuntu kernel source")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


_CERT_CONFIG_RE: re.Pattern[str] = re.compile(
    r'^(CONFIG_SYSTEM_TRUSTED_KEYS|CONFIG_SYSTEM_REVOCATION_KEYS|CONFIG_MODULE_SIG_KEY)="(.+)"$'
)


def _sanitize_cert_configs(source_dir: Path) -> None:
    """Clear cert/key config values that reference non-existent files.

    Ubuntu kernels ship configs pointing at Canonical-internal ``.pem``
    files (e.g. ``debian/canonical-certs.pem``).  These don't exist
    outside Canonical's build environment, causing ``make bindeb-pkg``
    to fail.  This function sets such entries to ``""`` so the build
    can proceed.
    """
    config_file = source_dir / ".config"
    if not config_file.exists():
        return

    lines = config_file.read_text(encoding="utf-8").splitlines(keepends=True)
    changed: list[str] = []
    new_lines: list[str] = []

    for line in lines:
        m = _CERT_CONFIG_RE.match(line.rstrip("\n"))
        if m:
            key, value = m.group(1), m.group(2)
            ref_path = source_dir / value
            if not ref_path.exists():
                ending = "\n" if line.endswith("\n") else ""
                new_lines.append(f'{key}=""{ending}')
                changed.append(f'{key}={value!r} -> ""')
                continue
        new_lines.append(line)

    if changed:
        config_file.write_text("".join(new_lines), encoding="utf-8")
        for entry in changed:
            log.info("Sanitized cert config: %s", entry)
    else:
        log.debug("No cert config entries needed sanitizing")


def configure_kernel(
    source_dir: Path,
    config_path: Path | None = None,
) -> None:
    """Apply config and run ``make olddefconfig``."""
    if config_path is not None:
        dest = source_dir / ".config"
        if config_path.resolve() != dest.resolve():
            shutil.copy2(config_path, dest)
            log.info("Copied config from %s", config_path)
        else:
            log.info("Config already at %s — skipping copy", dest)
    run_cmd(["make", "olddefconfig"], cwd=source_dir)
    _sanitize_cert_configs(source_dir)


def _make_env() -> dict[str, str] | None:
    """Return env with ccache PATH prepend if available."""
    if has_ccache():
        path = os.environ.get("PATH", "")
        return {"PATH": f"/usr/lib/ccache:{path}"}
    return None


def build_kernel(
    source_dir: Path,
    jobs: int | None = None,
    log_file: Path | None = None,
) -> None:
    """Compile the kernel with auto-dependency retry."""
    j = jobs if jobs is not None else compute_optimal_jobs()
    cmd = ["make", f"-j{j}"]
    env = _make_env()
    log.info("Building kernel with %d parallel jobs ...", j)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if log_file:
                _run_streaming(
                    cmd,
                    cwd=source_dir,
                    log_file=log_file,
                    env=env,
                )
            else:
                run_cmd(cmd, cwd=source_dir, env=env)
            return
        except subprocess.CalledProcessError:
            if attempt == MAX_RETRIES:
                raise BuildError(f"Build failed after {MAX_RETRIES} attempts") from None
            log.warning(
                "Build failed (attempt %d/%d) — installing deps and retrying ...",
                attempt,
                MAX_RETRIES,
            )
            ensure_build_deps()


def build_deb_package(
    source_dir: Path,
    jobs: int | None = None,
    log_file: Path | None = None,
) -> None:
    """Generate ``.deb`` packages via ``make bindeb-pkg``."""
    j = jobs if jobs is not None else compute_optimal_jobs()
    cmd = ["make", f"-j{j}", "bindeb-pkg"]
    env = _make_env()
    log.info("Building .deb packages ...")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if log_file:
                _run_streaming(
                    cmd,
                    cwd=source_dir,
                    log_file=log_file,
                    env=env,
                )
            else:
                run_cmd(cmd, cwd=source_dir, env=env)
            return
        except subprocess.CalledProcessError:
            if attempt == MAX_RETRIES:
                raise BuildError(f"Package build failed after {MAX_RETRIES} attempts") from None
            log.warning(
                "Package build failed (attempt %d/%d) — installing deps and retrying ...",
                attempt,
                MAX_RETRIES,
            )
            install_packages(BUILD_DEPS)


def install_kernel(source_dir: Path) -> None:
    """Install a compiled kernel."""
    log.info("Installing modules ...")
    run_cmd(["sudo", "make", "modules_install"], cwd=source_dir)
    log.info("Installing kernel ...")
    run_cmd(["sudo", "make", "install"], cwd=source_dir)
    log.info("Kernel installed successfully")


# ---------------------------------------------------------------------------
# Kernel signing
# ---------------------------------------------------------------------------


def generate_signing_key(
    dest_dir: Path,
) -> tuple[Path, Path]:
    """Generate a self-signed key pair for kernel signing."""
    key_path = dest_dir / "kernel-signing-key.pem"
    cert_path = dest_dir / "kernel-signing-cert.pem"

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
            "365",
            "-subj",
            "/CN=Kernel Signing Key",
        ]
    )

    # Restrict private key permissions
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    log.info("Generated signing key pair in %s", dest_dir)
    return key_path, cert_path


def sign_kernel(
    source_dir: Path,
    private_key: Path,
    certificate: Path,
) -> None:
    """Sign kernel using in-tree ``scripts/sign-file``."""
    sign_tool = source_dir / "scripts" / "sign-file"
    if not sign_tool.exists():
        raise FileNotFoundError(f"Sign tool not found: {sign_tool}")

    vmlinux = source_dir / "vmlinux"
    if not vmlinux.exists():
        raise FileNotFoundError(f"vmlinux not found — build the kernel first: {vmlinux}")

    log.info("Signing vmlinux ...")
    run_cmd(
        [
            str(sign_tool),
            "sha512",
            str(private_key),
            str(certificate),
            str(vmlinux),
        ]
    )
    log.info("Kernel signed successfully")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def numbered_menu(title: str, options: list[str]) -> int:
    """Display a numbered menu and return 0-based index."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    for i, option in enumerate(options, 1):
        print(f"  {i}) {option}")
    print()

    while True:
        try:
            raw = input("Select an option: ").strip()
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
        except ValueError:
            pass
        except EOFError:
            raise SystemExit("EOF received \u2014 aborting menu") from None
        print(f"  Invalid choice \u2014 enter a number between 1 and {len(options)}")


def prompt_yes_no(question: str) -> bool:
    """Prompt with a yes/no question."""
    while True:
        try:
            raw = input(f"{question} [y/n]: ").strip().lower()
        except EOFError:
            raise SystemExit("EOF received \u2014 aborting prompt") from None
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter 'y' or 'n'")


def setup_logging(
    log_file: Path | None = None,
    verbose: bool = True,
) -> None:
    """Configure logging for the kernel builder."""
    handlers: list[logging.Handler] = []

    if verbose:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        handlers.append(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), mode="a")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))
        handlers.append(fh)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)
