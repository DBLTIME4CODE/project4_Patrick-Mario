"""Tests for myproject.kernel_builder."""

from __future__ import annotations

import hashlib
import lzma
import os
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import myproject.kernel_builder as kb_module
from myproject.kernel_builder import (
    KERNEL_ORG_SIGNING_KEYS,
    MAX_INPUT_LENGTH,
    MAX_RETRIES,
    BuildError,
    ValidationError,
    _available_ram_gb,
    _cpu_count,
    _ensure_kernel_org_keys,
    _kernel_sig_url,
    _kernel_url,
    _normalize_kernel_version,
    _parse_missing_deps,
    _sanitize_cert_configs,
    build_deb_package,
    build_kernel,
    check_flash_kernel,
    compute_optimal_jobs,
    configure_kernel,
    download_kernel,
    enforce_locale,
    extract_running_config,
    fetch_latest_version,
    fetch_ubuntu_source,
    generate_signing_key,
    get_running_kernel,
    has_ccache,
    install_kernel,
    install_packages,
    numbered_menu,
    prompt_yes_no,
    run_cmd,
    safe_extract_tarball,
    setup_logging,
    sign_kernel,
    validate_input,
    validate_kernel_version,
    validate_url_domain,
    verify_checksum,
    verify_gpg_signature,
)

# ===================================================================
# validate_input
# ===================================================================


class TestValidateInput:
    """Whitelist: only [0-9a-zA-Z.-] allowed."""

    @pytest.mark.parametrize(
        "value",
        [
            "6.8.1",
            "linux-6.8.1",
            "v5.15",
            "abc123",
            "A.B-C",
        ],
    )
    def test_valid_inputs_accepted(self, value: str) -> None:
        assert validate_input(value, "test") == value

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_input("", "version")

    def test_null_byte_raises(self) -> None:
        with pytest.raises(ValidationError, match="null bytes"):
            validate_input("6.8\x001", "version")

    def test_over_length_raises(self) -> None:
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_input("a" * (MAX_INPUT_LENGTH + 1), "version")

    @pytest.mark.parametrize(
        "value",
        [
            "6.8 1",
            "6.8;rm -rf /",
            "`whoami`",
            "../etc/passwd",
            "ver$ION",
            "a|b",
            "a&b",
            "foo\nbar",
        ],
    )
    def test_dangerous_inputs_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            validate_input(value, "version")

    def test_is_valueerror_subclass(self) -> None:
        with pytest.raises(ValueError):
            validate_input("", "test")


# ===================================================================
# validate_kernel_version
# ===================================================================


class TestValidateKernelVersion:
    """Relaxed pattern for uname-derived versions: [0-9a-zA-Z.\\-+_]."""

    @pytest.mark.parametrize(
        "value",
        [
            "6.5.0-44-generic",
            "6.5.0+custom",
            "6.8.1",
            "5.15.0-1024-azure",
            "6.5.0_rc1",
            "6.5.0+custom_build",
            "A.B-C",
        ],
    )
    def test_valid_uname_versions_accepted(self, value: str) -> None:
        assert validate_kernel_version(value) == value

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_kernel_version("")

    def test_null_byte_raises(self) -> None:
        with pytest.raises(ValidationError, match="null bytes"):
            validate_kernel_version("6.5\x001")

    def test_over_length_raises(self) -> None:
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validate_kernel_version("a" * (MAX_INPUT_LENGTH + 1))

    @pytest.mark.parametrize(
        "value",
        [
            "6.5;rm -rf /",
            "`whoami`",
            "../etc/passwd",
            "ver$ION",
            "a|b",
            "a&b",
            "foo\nbar",
            "6.5 0",
        ],
    )
    def test_dangerous_inputs_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            validate_kernel_version(value)


# ===================================================================
# validate_url_domain
# ===================================================================


class TestValidateUrlDomain:
    def test_allowed_domain(self) -> None:
        url = "https://cdn.kernel.org/pub/linux/kernel/v6.x/f.xz"
        assert validate_url_domain(url) == url

    def test_www_kernel_org(self) -> None:
        url = "https://www.kernel.org/releases.json"
        assert validate_url_domain(url) == url

    def test_http_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTPS"):
            validate_url_domain("http://cdn.kernel.org/pub/linux/kernel/v6.x/f")

    def test_evil_domain_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not in the allowed"):
            validate_url_domain("https://evil.com/linux-6.8.1.tar.xz")

    def test_domain_with_port_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not in the allowed"):
            validate_url_domain("https://evil.com:443/linux-6.8.1.tar.xz")


# ===================================================================
# enforce_locale
# ===================================================================


class TestEnforceLocale:
    def test_sets_env_vars(self) -> None:
        enforce_locale()
        assert os.environ["LANG"] == "en_US.UTF-8"
        assert os.environ["LC_ALL"] == "en_US.UTF-8"


# ===================================================================
# _kernel_url / _kernel_sig_url
# ===================================================================


class TestKernelUrl:
    def test_v6(self) -> None:
        url = _kernel_url("6.8.1")
        assert url == ("https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.8.1.tar.xz")

    def test_v5(self) -> None:
        url = _kernel_url("5.15.100")
        assert url == ("https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.15.100.tar.xz")

    def test_sig_url(self) -> None:
        url = _kernel_sig_url("6.8.1")
        assert url == ("https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.8.1.tar.sign")

    def test_dot_zero_normalized(self) -> None:
        url = _kernel_url("6.5.0")
        assert url == ("https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.5.tar.xz")

    def test_dot_zero_sig_normalized(self) -> None:
        url = _kernel_sig_url("6.5.0")
        assert url == ("https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.5.tar.sign")


# ===================================================================
# _normalize_kernel_version
# ===================================================================


class TestNormalizeKernelVersion:
    def test_strips_trailing_zero(self) -> None:
        assert _normalize_kernel_version("6.5.0") == "6.5"

    def test_keeps_nonzero_patch(self) -> None:
        assert _normalize_kernel_version("6.5.1") == "6.5.1"

    def test_keeps_four_part(self) -> None:
        assert _normalize_kernel_version("5.4.0.0") == "5.4.0.0"

    def test_keeps_two_part(self) -> None:
        assert _normalize_kernel_version("6.5") == "6.5"


# ===================================================================
# run_cmd
# ===================================================================


class TestRunCmd:
    @patch("myproject.kernel_builder.subprocess.run")
    def test_basic_call(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=["echo", "hi"], returncode=0)
        run_cmd(["echo", "hi"])
        mock_run.assert_called_once()
        kw = mock_run.call_args[1]
        assert kw["check"] is True
        assert kw["text"] is True

    @patch("myproject.kernel_builder.subprocess.run")
    def test_capture_mode(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["echo"], returncode=0, stdout="ok\n"
        )
        result = run_cmd(["echo"], capture=True)
        assert result.stdout == "ok\n"

    @patch("myproject.kernel_builder.subprocess.run")
    def test_env_merging(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        run_cmd(["echo"], env={"MY_VAR": "hello"})
        merged = mock_run.call_args[1]["env"]
        assert merged is not None
        assert merged["MY_VAR"] == "hello"

    @patch("myproject.kernel_builder.subprocess.run")
    def test_cwd_forwarded(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        run_cmd(["ls"], cwd=tmp_path)
        assert mock_run.call_args[1]["cwd"] == tmp_path


# ===================================================================
# get_running_kernel
# ===================================================================


class TestGetRunningKernel:
    @patch("myproject.kernel_builder.run_cmd")
    def test_returns_stripped(self, mock_cmd: MagicMock) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(
            args=["uname", "-r"],
            returncode=0,
            stdout="6.5.0-44-generic\n",
        )
        assert get_running_kernel() == "6.5.0-44-generic"


# ===================================================================
# check_flash_kernel
# ===================================================================


class TestCheckFlashKernel:
    @patch("myproject.kernel_builder.run_cmd")
    def test_installed(self, mock_cmd: MagicMock) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert check_flash_kernel() is True

    @patch("myproject.kernel_builder.run_cmd")
    def test_not_installed(self, mock_cmd: MagicMock) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=1)
        assert check_flash_kernel() is False


# ===================================================================
# install_packages
# ===================================================================


class TestInstallPackages:
    @patch("myproject.kernel_builder.run_cmd")
    def test_calls_update_and_install(self, mock_cmd: MagicMock) -> None:
        install_packages(["vim", "git"])
        assert mock_cmd.call_count == 2
        update = mock_cmd.call_args_list[0][0][0]
        install = mock_cmd.call_args_list[1][0][0]
        assert update == ["sudo", "apt-get", "update", "-qq"]
        assert install == [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "-qq",
            "vim",
            "git",
        ]


# ===================================================================
# extract_running_config
# ===================================================================


class TestExtractRunningConfig:
    @patch(
        "myproject.kernel_builder.get_running_kernel",
        return_value="6.5.0-44-generic",
    )
    def test_no_config_found_raises(self, mock_k: MagicMock, tmp_path: Path) -> None:
        with pytest.raises(
            FileNotFoundError,
            match="No kernel config found",
        ):
            extract_running_config(tmp_path)


# ===================================================================
# download_kernel
# ===================================================================


class TestDownloadKernel:
    @patch("myproject.kernel_builder.run_cmd")
    def test_invalid_version_rejected(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            download_kernel("6.8;rm -rf /", tmp_path)
        mock_cmd.assert_not_called()

    @patch("myproject.kernel_builder.safe_extract_tarball")
    @patch("myproject.kernel_builder.run_cmd")
    def test_downloads_and_extracts(
        self,
        mock_cmd: MagicMock,
        mock_extract: MagicMock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "linux-6.8.1").mkdir()
        result = download_kernel("6.8.1", tmp_path)
        assert result == tmp_path / "linux-6.8.1"
        assert mock_cmd.call_count >= 1

    @patch("myproject.kernel_builder.safe_extract_tarball")
    @patch("myproject.kernel_builder.run_cmd")
    def test_skips_extraction_when_source_dir_exists(
        self,
        mock_cmd: MagicMock,
        mock_extract: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Second run should reuse existing source dir, not re-extract."""
        (tmp_path / "linux-6.8.1").mkdir()
        result = download_kernel("6.8.1", tmp_path)
        assert result == tmp_path / "linux-6.8.1"
        mock_extract.assert_not_called()

    @patch("myproject.kernel_builder.safe_extract_tarball")
    @patch("myproject.kernel_builder.run_cmd")
    def test_missing_source_dir_raises(
        self,
        mock_cmd: MagicMock,
        mock_extract: MagicMock,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(
            FileNotFoundError,
            match="Expected source directory",
        ):
            download_kernel("6.8.1", tmp_path)

    @patch("myproject.kernel_builder.verify_gpg_signature")
    @patch("myproject.kernel_builder.safe_extract_tarball")
    @patch("myproject.kernel_builder.run_cmd")
    def test_gpg_verifies_decompressed_tar(
        self,
        mock_cmd: MagicMock,
        mock_extract: MagicMock,
        mock_verify: MagicMock,
        tmp_path: Path,
    ) -> None:
        """GPG verification must run against the .tar, not .tar.xz."""
        # Create a real .tar.xz so lzma.open succeeds
        tar_path = tmp_path / "linux-6.8.1.tar"
        tar_path.write_bytes(b"fake tar content")
        xz_path = tmp_path / "linux-6.8.1.tar.xz"
        with lzma.open(xz_path, "wb") as f:
            f.write(b"fake tar content")
        tar_path.unlink()  # cleanup; download_kernel will recreate

        # Simulate wget signature download succeeding
        sig_path = tmp_path / "linux-6.8.1.tar.sign"
        sig_path.write_bytes(b"fake sig")
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        mock_verify.return_value = True

        (tmp_path / "linux-6.8.1").mkdir()
        download_kernel("6.8.1", tmp_path)

        # Assert verify was called with .tar (not .tar.xz)
        mock_verify.assert_called_once()
        verified_path = mock_verify.call_args[0][0]
        assert verified_path.suffix == ".tar"
        assert verified_path.name == "linux-6.8.1.tar"

        # .tar should be cleaned up after verification
        assert not (tmp_path / "linux-6.8.1.tar").exists()


# ===================================================================
# fetch_ubuntu_source
# ===================================================================


class TestFetchUbuntuSource:
    @patch("myproject.kernel_builder.run_cmd")
    @patch(
        "myproject.kernel_builder.get_running_kernel",
        return_value="6.5.0-44-generic",
    )
    def test_finds_source_dir(
        self,
        mock_k: MagicMock,
        mock_cmd: MagicMock,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "linux-6.5.0").mkdir()
        result = fetch_ubuntu_source(tmp_path)
        assert result == tmp_path / "linux-6.5.0"

    @patch("myproject.kernel_builder.run_cmd")
    @patch(
        "myproject.kernel_builder.get_running_kernel",
        return_value="6.5.0-44-generic",
    )
    def test_no_source_dir_raises(
        self,
        mock_k: MagicMock,
        mock_cmd: MagicMock,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(FileNotFoundError, match="Could not locate"):
            fetch_ubuntu_source(tmp_path)


# ===================================================================
# configure_kernel
# ===================================================================


class TestConfigureKernel:
    @patch("myproject.kernel_builder.run_cmd")
    def test_with_config_file(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        config = tmp_path / "myconfig"
        config.write_text("CONFIG_X86=y\n")
        configure_kernel(tmp_path, config)
        text = (tmp_path / ".config").read_text()
        assert text == "CONFIG_X86=y\n"
        assert mock_cmd.call_count == 2  # olddefconfig runs twice (before + after sanitization)

    @patch("myproject.kernel_builder.run_cmd")
    def test_without_config_file(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        configure_kernel(tmp_path)
        assert mock_cmd.call_count == 2  # olddefconfig runs twice (before + after sanitization)
        assert mock_cmd.call_args[0][0] == ["make", "olddefconfig"]

    @patch("myproject.kernel_builder.run_cmd")
    def test_same_file_no_error(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """config_path == source_dir/.config must not raise SameFileError."""
        dest = tmp_path / ".config"
        dest.write_text("CONFIG_X86=y\n")
        configure_kernel(tmp_path, dest)
        # File should be unchanged
        assert dest.read_text() == "CONFIG_X86=y\n"
        assert mock_cmd.call_count == 2  # olddefconfig runs twice (before + after sanitization)

    @patch("myproject.kernel_builder.run_cmd")
    def test_clean_runs_mrproper(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """clean=True should run make mrproper before olddefconfig."""
        config = tmp_path / "myconfig"
        config.write_text("CONFIG_X86=y\n")
        configure_kernel(tmp_path, config, clean=True)
        calls = [c[0][0] for c in mock_cmd.call_args_list]
        assert calls[0] == ["make", "mrproper"]
        assert calls[1] == ["make", "olddefconfig"]
        assert mock_cmd.call_count == 3  # mrproper + 2x olddefconfig


# ===================================================================
# _sanitize_cert_configs
# ===================================================================


class TestSanitizeCertConfigs:
    def test_missing_certs_cleared(self, tmp_path: Path) -> None:
        """Configs referencing non-existent cert files are set to empty."""
        config = tmp_path / ".config"
        config.write_text(
            'CONFIG_SYSTEM_TRUSTED_KEYS="debian/canonical-certs.pem"\n'
            'CONFIG_SYSTEM_REVOCATION_KEYS="debian/canonical-revoked-certs.pem"\n'
            'CONFIG_MODULE_SIG_KEY="certs/signing_key.pem"\n'
            "CONFIG_X86=y\n"
        )
        _sanitize_cert_configs(tmp_path)
        result = config.read_text()
        assert 'CONFIG_SYSTEM_TRUSTED_KEYS=""' in result
        assert 'CONFIG_SYSTEM_REVOCATION_KEYS=""' in result
        assert 'CONFIG_MODULE_SIG_KEY=""' in result
        assert "CONFIG_X86=y" in result

    def test_existing_certs_preserved(self, tmp_path: Path) -> None:
        """Configs referencing files that DO exist are left alone."""
        cert_dir = tmp_path / "debian"
        cert_dir.mkdir()
        (cert_dir / "canonical-certs.pem").write_text("cert")
        config = tmp_path / ".config"
        config.write_text('CONFIG_SYSTEM_TRUSTED_KEYS="debian/canonical-certs.pem"\nCONFIG_X86=y\n')
        _sanitize_cert_configs(tmp_path)
        result = config.read_text()
        assert 'CONFIG_SYSTEM_TRUSTED_KEYS="debian/canonical-certs.pem"' in result

    def test_already_empty_left_alone(self, tmp_path: Path) -> None:
        """Configs already set to empty string are not changed."""
        config = tmp_path / ".config"
        original = 'CONFIG_SYSTEM_TRUSTED_KEYS=""\nCONFIG_SYSTEM_REVOCATION_KEYS=""\nCONFIG_X86=y\n'
        config.write_text(original)
        _sanitize_cert_configs(tmp_path)
        assert config.read_text() == original

    def test_non_cert_configs_untouched(self, tmp_path: Path) -> None:
        """Non-cert config keys are never modified."""
        config = tmp_path / ".config"
        original = 'CONFIG_X86=y\nCONFIG_LOCALVERSION="-custom"\n# CONFIG_DEBUG_INFO is not set\n'
        config.write_text(original)
        _sanitize_cert_configs(tmp_path)
        assert config.read_text() == original

    def test_no_config_file_is_noop(self, tmp_path: Path) -> None:
        """Gracefully does nothing when .config doesn't exist."""
        _sanitize_cert_configs(tmp_path)  # should not raise

    def test_module_sig_disabled_when_key_cleared(self, tmp_path: Path) -> None:
        """SIG, SIG_ALL, and SIG_FORCE are disabled when key is cleared."""
        config = tmp_path / ".config"
        config.write_text(
            'CONFIG_MODULE_SIG_KEY="certs/signing_key.pem"\n'
            "CONFIG_MODULE_SIG=y\n"
            "CONFIG_MODULE_SIG_ALL=y\n"
            "CONFIG_MODULE_SIG_FORCE=y\n"
            "CONFIG_X86=y\n"
        )
        _sanitize_cert_configs(tmp_path)
        result = config.read_text()
        assert 'CONFIG_MODULE_SIG_KEY=""' in result
        assert "# CONFIG_MODULE_SIG is not set" in result
        assert "# CONFIG_MODULE_SIG_ALL is not set" in result
        assert "# CONFIG_MODULE_SIG_FORCE is not set" in result
        assert "CONFIG_MODULE_SIG=y" not in result
        assert "CONFIG_MODULE_SIG_ALL=y" not in result
        assert "CONFIG_MODULE_SIG_FORCE=y" not in result
        assert "CONFIG_X86=y" in result

    def test_module_sig_stays_when_key_exists(self, tmp_path: Path) -> None:
        """Module signing is NOT disabled when the key file exists."""
        certs_dir = tmp_path / "certs"
        certs_dir.mkdir()
        (certs_dir / "signing_key.pem").write_text("key")
        config = tmp_path / ".config"
        config.write_text(
            'CONFIG_MODULE_SIG_KEY="certs/signing_key.pem"\n'
            "CONFIG_MODULE_SIG=y\n"
            "CONFIG_MODULE_SIG_ALL=y\n"
            "CONFIG_X86=y\n"
        )
        _sanitize_cert_configs(tmp_path)
        result = config.read_text()
        assert 'CONFIG_MODULE_SIG_KEY="certs/signing_key.pem"' in result
        assert "CONFIG_MODULE_SIG=y" in result
        assert "CONFIG_MODULE_SIG_ALL=y" in result

    @patch("myproject.kernel_builder.run_cmd")
    def test_configure_kernel_calls_sanitize(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """configure_kernel invokes _sanitize_cert_configs between two olddefconfig runs."""
        config = tmp_path / ".config"
        config.write_text('CONFIG_SYSTEM_TRUSTED_KEYS="debian/canonical-certs.pem"\n')
        configure_kernel(tmp_path)
        # After configure_kernel, the missing cert should be cleared
        assert 'CONFIG_SYSTEM_TRUSTED_KEYS=""' in config.read_text()
        assert mock_cmd.call_count == 2


# ===================================================================
# compute_optimal_jobs
# ===================================================================


class TestCpuCount:
    @patch("os.cpu_count", return_value=8)
    def test_returns_count(self, mock_cpu: MagicMock) -> None:
        assert _cpu_count() == 8

    @patch("os.cpu_count", return_value=None)
    def test_none_returns_one(self, mock_cpu: MagicMock) -> None:
        assert _cpu_count() == 1


class TestComputeOptimalJobs:
    @patch(
        "myproject.kernel_builder._available_ram_gb",
        return_value=16.0,
    )
    @patch(
        "myproject.kernel_builder._cpu_count",
        return_value=8,
    )
    def test_cpu_limited(self, mock_cpu: MagicMock, mock_ram: MagicMock) -> None:
        assert compute_optimal_jobs() == 8

    @patch(
        "myproject.kernel_builder._available_ram_gb",
        return_value=2.0,
    )
    @patch(
        "myproject.kernel_builder._cpu_count",
        return_value=8,
    )
    def test_ram_limited(self, mock_cpu: MagicMock, mock_ram: MagicMock) -> None:
        assert compute_optimal_jobs() == 4

    @patch(
        "myproject.kernel_builder._available_ram_gb",
        return_value=0.3,
    )
    @patch(
        "myproject.kernel_builder._cpu_count",
        return_value=4,
    )
    def test_very_low_ram(self, mock_cpu: MagicMock, mock_ram: MagicMock) -> None:
        assert compute_optimal_jobs() == 1


class TestAvailableRamGb:
    def test_fallback(self) -> None:
        with patch(
            "builtins.open",
            side_effect=OSError("no procfs"),
        ):
            assert _available_ram_gb() == 4.0


# ===================================================================
# build_kernel
# ===================================================================


class TestBuildKernel:
    @patch(
        "myproject.kernel_builder.compute_optimal_jobs",
        return_value=4,
    )
    @patch("myproject.kernel_builder.run_cmd")
    def test_success(
        self,
        mock_cmd: MagicMock,
        mock_jobs: MagicMock,
        tmp_path: Path,
    ) -> None:
        build_kernel(tmp_path, jobs=4)
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[0][0] == ["make", "-j4"]

    @patch("myproject.kernel_builder.ensure_build_deps")
    @patch("myproject.kernel_builder.run_cmd")
    def test_retry_on_failure(
        self,
        mock_cmd: MagicMock,
        mock_deps: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_cmd.side_effect = [
            subprocess.CalledProcessError(2, "make"),
            subprocess.CompletedProcess(args=["make"], returncode=0),
        ]
        build_kernel(tmp_path, jobs=2)
        assert mock_deps.called
        assert mock_cmd.call_count == 2

    @patch("myproject.kernel_builder.ensure_build_deps")
    @patch("myproject.kernel_builder.run_cmd")
    def test_raises_after_max_retries(
        self,
        mock_cmd: MagicMock,
        mock_deps: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_cmd.side_effect = subprocess.CalledProcessError(2, "make")
        with pytest.raises(BuildError, match="failed after"):
            build_kernel(tmp_path, jobs=2)
        assert mock_cmd.call_count == MAX_RETRIES


# ===================================================================
# build_deb_package
# ===================================================================


class TestBuildDebPackage:
    @patch(
        "myproject.kernel_builder.compute_optimal_jobs",
        return_value=4,
    )
    @patch("myproject.kernel_builder.run_cmd")
    def test_success(
        self,
        mock_cmd: MagicMock,
        mock_jobs: MagicMock,
        tmp_path: Path,
    ) -> None:
        build_deb_package(tmp_path, jobs=4)
        mock_cmd.assert_called_once()
        assert mock_cmd.call_args[0][0] == ["make", "-j4", "bindeb-pkg"]

    @patch("myproject.kernel_builder.install_packages")
    @patch("myproject.kernel_builder.run_cmd")
    def test_retry_parses_missing_deps(
        self,
        mock_cmd: MagicMock,
        mock_install: MagicMock,
        tmp_path: Path,
    ) -> None:
        """On failure with dpkg-checkbuilddeps error, installs parsed deps."""
        exc = subprocess.CalledProcessError(2, "make")
        exc.stderr = (
            "dpkg-checkbuilddeps: error: Unmet build dependencies: libdw-dev:native libfoo:native"
        )
        mock_cmd.side_effect = [
            exc,
            subprocess.CompletedProcess(args=["make"], returncode=0),
        ]
        build_deb_package(tmp_path, jobs=2)
        mock_install.assert_called_once_with(["libdw-dev", "libfoo"])

    @patch("myproject.kernel_builder.install_packages")
    @patch("myproject.kernel_builder.run_cmd")
    def test_retry_falls_back_to_build_deps(
        self,
        mock_cmd: MagicMock,
        mock_install: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No parseable stderr → falls back to full BUILD_DEPS list."""
        mock_cmd.side_effect = [
            subprocess.CalledProcessError(2, "make"),
            subprocess.CompletedProcess(args=["make"], returncode=0),
        ]
        build_deb_package(tmp_path, jobs=2)
        from myproject.kernel_builder import BUILD_DEPS

        mock_install.assert_called_once_with(BUILD_DEPS)

    @patch("myproject.kernel_builder.install_packages")
    @patch("myproject.kernel_builder.run_cmd")
    def test_raises_after_max_retries(
        self,
        mock_cmd: MagicMock,
        mock_install: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_cmd.side_effect = subprocess.CalledProcessError(2, "make")
        with pytest.raises(BuildError, match="failed after"):
            build_deb_package(tmp_path, jobs=2)
        assert mock_cmd.call_count == MAX_RETRIES


# ===================================================================
# install_kernel
# ===================================================================


class TestInstallKernel:
    @patch("myproject.kernel_builder.run_cmd")
    def test_modules_then_kernel(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        install_kernel(tmp_path)
        assert mock_cmd.call_count == 2
        assert mock_cmd.call_args_list[0][0][0] == ["sudo", "make", "modules_install"]
        assert mock_cmd.call_args_list[1][0][0] == ["sudo", "make", "install"]


# ===================================================================
# sign_kernel
# ===================================================================


class TestSignKernel:
    def test_missing_sign_tool_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Sign tool"):
            sign_kernel(
                tmp_path,
                Path("key.pem"),
                Path("cert.pem"),
            )

    def test_missing_vmlinux_raises(self, tmp_path: Path) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "sign-file").touch()
        with pytest.raises(FileNotFoundError, match="vmlinux"):
            sign_kernel(
                tmp_path,
                Path("key.pem"),
                Path("cert.pem"),
            )

    @patch("myproject.kernel_builder.run_cmd")
    def test_signs_successfully(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "sign-file").touch()
        (tmp_path / "vmlinux").touch()
        sign_kernel(
            tmp_path,
            Path("key.pem"),
            Path("cert.pem"),
        )
        mock_cmd.assert_called_once()
        cmd = mock_cmd.call_args[0][0]
        assert cmd[1] == "sha512"


# ===================================================================
# generate_signing_key
# ===================================================================


class TestGenerateSigningKey:
    @patch("myproject.kernel_builder.run_cmd")
    def test_generates_key(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        key = tmp_path / "kernel-signing-key.pem"
        cert = tmp_path / "kernel-signing-cert.pem"
        key.write_text("key")
        cert.write_text("cert")
        k, c = generate_signing_key(tmp_path)
        assert k == key
        assert c == cert
        mock_cmd.assert_called_once()
        if os.name != "nt":
            mode = key.stat().st_mode & 0o777
            assert mode == 0o600


# ===================================================================
# verify_checksum
# ===================================================================


class TestVerifyChecksum:
    def test_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        verify_checksum(f, expected)

    def test_invalid_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        with pytest.raises(ValidationError, match="SHA-256"):
            verify_checksum(f, "bad" * 21 + "bad")


# ===================================================================
# verify_gpg_signature
# ===================================================================


class TestVerifyGpgSignature:
    @patch("myproject.kernel_builder.run_cmd")
    def test_valid(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        f = tmp_path / "file.tar.xz"
        sig = tmp_path / "file.tar.sign"
        f.touch()
        sig.touch()
        assert verify_gpg_signature(f, sig) is True

    @patch("myproject.kernel_builder.run_cmd")
    def test_invalid(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=1, stderr="BAD sig")
        f = tmp_path / "file.tar.xz"
        sig = tmp_path / "file.tar.sign"
        f.touch()
        sig.touch()
        assert verify_gpg_signature(f, sig) is False


# ===================================================================
# _ensure_kernel_org_keys
# ===================================================================


class TestEnsureKernelOrgKeys:
    """Tests for GPG key import helper."""

    def setup_method(self) -> None:
        """Reset the module-level import flag before each test."""
        kb_module._gpg_keys_imported = False

    @patch("myproject.kernel_builder.run_cmd")
    def test_any_key_already_in_keyring(self, mock_cmd: MagicMock) -> None:
        """If ANY key is already present, no keyserver call is made."""
        # First key present, second not — still succeeds
        mock_cmd.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0),  # list-keys key0 → found
        ]
        assert _ensure_kernel_org_keys() is True
        assert kb_module._gpg_keys_imported is True
        for call in mock_cmd.call_args_list:
            assert "--recv-keys" not in call[0][0]

    @patch("myproject.kernel_builder.run_cmd")
    def test_imports_keys_individually(self, mock_cmd: MagicMock) -> None:
        """Keys not present → imports each individually → any present → True."""
        call_index = {"n": 0}

        def side_effect(cmd: list[str], **kwargs):
            call_index["n"] += 1
            if "--list-keys" in cmd:
                # Initial any() check: both missing
                # Post-import checks: first key present, second not
                if call_index["n"] <= len(KERNEL_ORG_SIGNING_KEYS):
                    return subprocess.CompletedProcess(args=cmd, returncode=2)
                # After imports, first key present
                if KERNEL_ORG_SIGNING_KEYS[0] in cmd:
                    return subprocess.CompletedProcess(args=cmd, returncode=0)
                return subprocess.CompletedProcess(args=cmd, returncode=2)
            if "--recv-keys" in cmd:
                # First key import succeeds, second fails
                if KERNEL_ORG_SIGNING_KEYS[0] in cmd:
                    return subprocess.CompletedProcess(args=cmd, returncode=0)
                return subprocess.CompletedProcess(args=cmd, returncode=2)
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        mock_cmd.side_effect = side_effect
        assert _ensure_kernel_org_keys() is True
        assert kb_module._gpg_keys_imported is True
        # Each key should have its own --recv-keys call (individual import)
        recv_calls = [c for c in mock_cmd.call_args_list if "--recv-keys" in c[0][0]]
        for call in recv_calls:
            # Only one key per call (individual import)
            keys_in_call = [arg for arg in call[0][0] if len(arg) == 40 and arg.isalnum()]
            assert len(keys_in_call) == 1

    @patch("myproject.kernel_builder.run_cmd")
    def test_no_fallback_keyserver(self, mock_cmd: MagicMock) -> None:
        """pgp.mit.edu must never be contacted."""
        mock_cmd.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stderr="timeout",
        )
        _ensure_kernel_org_keys()
        for call in mock_cmd.call_args_list:
            cmd_str = " ".join(call[0][0])
            assert "pgp.mit.edu" not in cmd_str

    @patch("myproject.kernel_builder.run_cmd")
    def test_all_keyservers_fail(self, mock_cmd: MagicMock) -> None:
        """All key imports fail → returns False."""
        mock_cmd.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stderr="keyserver unreachable",
        )
        assert _ensure_kernel_org_keys() is False
        assert kb_module._gpg_keys_imported is False

    @patch("myproject.kernel_builder.run_cmd")
    def test_only_calls_once_per_session(self, mock_cmd: MagicMock) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert _ensure_kernel_org_keys() is True
        assert _ensure_kernel_org_keys() is True
        first_call_count = mock_cmd.call_count
        _ensure_kernel_org_keys()
        assert mock_cmd.call_count == first_call_count

    @patch("myproject.kernel_builder.run_cmd")
    def test_retries_after_failure(self, mock_cmd: MagicMock) -> None:
        """A failed attempt should NOT set the flag, allowing retry."""
        mock_cmd.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stderr="timeout",
        )
        assert _ensure_kernel_org_keys() is False
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert _ensure_kernel_org_keys() is True


# ===================================================================
# _parse_missing_deps
# ===================================================================


class TestParseMissingDeps:
    def test_parses_single_dep(self) -> None:
        stderr = "dpkg-checkbuilddeps: error: Unmet build dependencies: libdw-dev:native"
        assert _parse_missing_deps(stderr) == ["libdw-dev"]

    def test_parses_multiple_deps(self) -> None:
        stderr = (
            "dpkg-checkbuilddeps: error: Unmet build dependencies: "
            "libdw-dev:native libfoo:native libbar"
        )
        assert _parse_missing_deps(stderr) == ["libdw-dev", "libfoo", "libbar"]

    def test_strips_version_constraints(self) -> None:
        stderr = "dpkg-checkbuilddeps: error: Unmet build dependencies: libdw-dev (>= 0.158)"
        assert _parse_missing_deps(stderr) == ["libdw-dev"]

    def test_returns_empty_for_unrelated_output(self) -> None:
        stderr = "make[1]: *** [Makefile:1234: vmlinux] Error 2"
        assert _parse_missing_deps(stderr) == []

    def test_returns_empty_for_empty_string(self) -> None:
        assert _parse_missing_deps("") == []


# ===================================================================
# safe_extract_tarball
# ===================================================================


class TestSafeExtractTarball:
    def test_normal_extraction(self, tmp_path: Path) -> None:
        tar_path = tmp_path / "test.tar"
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "file.txt").write_text("hello")
        with tarfile.open(tar_path, "w") as tf:
            tf.add(
                content_dir / "file.txt",
                arcname="pkg/file.txt",
            )
        dest = tmp_path / "out"
        dest.mkdir()
        safe_extract_tarball(tar_path, dest)
        assert (dest / "pkg" / "file.txt").read_text() == "hello"

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        tar_path = tmp_path / "evil.tar"
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo(name="../../../etc/evil")
            info.size = 0
            tf.addfile(info)
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(ValidationError, match="Path traversal"):
            safe_extract_tarball(tar_path, dest)


# ===================================================================
# has_ccache
# ===================================================================


class TestHasCcache:
    @patch("shutil.which", return_value="/usr/bin/ccache")
    def test_found(self, m: MagicMock) -> None:
        assert has_ccache() is True

    @patch("shutil.which", return_value=None)
    def test_not_found(self, m: MagicMock) -> None:
        assert has_ccache() is False


# ===================================================================
# fetch_latest_version
# ===================================================================


class TestFetchLatestVersion:
    @patch("myproject.kernel_builder.urlopen")
    def test_returns_version(self, mock_urlopen: MagicMock) -> None:
        body = b'{"latest_stable": {"version": "6.12.3"}}'
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        assert fetch_latest_version() == "6.12.3"


# ===================================================================
# numbered_menu
# ===================================================================


class TestNumberedMenu:
    @patch("builtins.input", return_value="2")
    def test_valid_choice(self, mock_input: MagicMock) -> None:
        assert numbered_menu("T", ["A", "B", "C"]) == 1

    @patch("builtins.input", side_effect=["0", "5", "2"])
    def test_rejects_out_of_range(self, mock_input: MagicMock) -> None:
        assert numbered_menu("T", ["A", "B", "C"]) == 1

    @patch("builtins.input", side_effect=["abc", "1"])
    def test_rejects_non_numeric(self, mock_input: MagicMock) -> None:
        assert numbered_menu("T", ["A", "B"]) == 0


# ===================================================================
# prompt_yes_no
# ===================================================================


class TestPromptYesNo:
    @patch("builtins.input", return_value="y")
    def test_y(self, m: MagicMock) -> None:
        assert prompt_yes_no("Continue?") is True

    @patch("builtins.input", return_value="yes")
    def test_yes(self, m: MagicMock) -> None:
        assert prompt_yes_no("Continue?") is True

    @patch("builtins.input", return_value="n")
    def test_n(self, m: MagicMock) -> None:
        assert prompt_yes_no("Continue?") is False

    @patch("builtins.input", return_value="no")
    def test_no(self, m: MagicMock) -> None:
        assert prompt_yes_no("Continue?") is False

    @patch("builtins.input", side_effect=["maybe", "yes"])
    def test_retries_on_bad(self, m: MagicMock) -> None:
        assert prompt_yes_no("Continue?") is True


# ===================================================================
# setup_logging
# ===================================================================


class TestSetupLogging:
    def test_console_only(self) -> None:
        setup_logging(verbose=True)

    def test_file_logging(self, tmp_path: Path) -> None:
        log_path = tmp_path / "sub" / "build.log"
        setup_logging(log_file=log_path, verbose=False)
        assert log_path.parent.exists()

    def test_both(self, tmp_path: Path) -> None:
        log_path = tmp_path / "build.log"
        setup_logging(log_file=log_path, verbose=True)
        assert log_path.parent.exists()


# ===================================================================
# kernel_cli.main — KeyboardInterrupt
# ===================================================================


class TestCliKeyboardInterrupt:
    @patch("myproject.kernel_cli._main_inner", side_effect=KeyboardInterrupt)
    def test_ctrl_c_gives_clean_exit(self, mock_inner: MagicMock) -> None:
        from myproject.kernel_cli import main

        with pytest.raises(SystemExit, match="Interrupted"):
            main()
