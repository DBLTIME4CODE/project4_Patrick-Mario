"""Tests for myproject.chroot_build."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myproject.chroot_build import (
    CHROOT_EXTRA_PACKAGES,
    CHROOT_MOUNT_POINTS,
    DEFAULT_MIRROR,
    DEFAULT_SUITE,
    _is_mounted,
    _mount_filesystems,
    _unmount_filesystems,
    _validate_chroot_path_for_removal,
    _validate_glob,
    chroot_kernel_build,
    copy_source_into_chroot,
    create_chroot,
    extract_artifacts,
    install_build_deps,
    managed_mounts,
    run_chroot_build,
    teardown_chroot,
    validate_mirror,
    validate_suite,
)
from myproject.kernel_builder import (
    BuildError,
    ValidationError,
)

# ===================================================================
# validate_suite
# ===================================================================


class TestValidateSuite:
    @pytest.mark.parametrize("suite", ["bookworm", "jammy", "noble", "sid"])
    def test_valid_suites(self, suite: str) -> None:
        assert validate_suite(suite) == suite

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_suite("")

    @pytest.mark.parametrize(
        "suite",
        ["book worm", "jammy;evil", "../etc", "a|b", "`cmd`"],
    )
    def test_dangerous_suite_rejected(self, suite: str) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            validate_suite(suite)


# ===================================================================
# validate_mirror
# ===================================================================


class TestValidateMirror:
    def test_http_accepted(self) -> None:
        assert validate_mirror("http://deb.debian.org/debian") == "http://deb.debian.org/debian"

    def test_https_accepted(self) -> None:
        url = "https://mirror.example.com/ubuntu"
        assert validate_mirror(url) == url

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            validate_mirror("")

    def test_ftp_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must use http"):
            validate_mirror("ftp://mirror.example.com/debian")

    def test_no_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must use http"):
            validate_mirror("deb.debian.org/debian")


# ===================================================================
# _validate_glob
# ===================================================================


class TestValidateGlob:
    @pytest.mark.parametrize("pattern", ["*.deb", "linux-*.deb", "foo.tar", "test_[0-9]"])
    def test_safe_patterns_accepted(self, pattern: str) -> None:
        assert _validate_glob(pattern) == pattern

    def test_recursive_double_star_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Recursive glob.*not allowed"):
            _validate_glob("**/*.deb")

    def test_double_star_alone_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Recursive glob.*not allowed"):
            _validate_glob("**")

    @pytest.mark.parametrize("pattern", ["*.deb;rm -rf /", "$(cmd)", "foo|bar"])
    def test_unsafe_chars_rejected(self, pattern: str) -> None:
        with pytest.raises(ValidationError, match="Unsafe glob"):
            _validate_glob(pattern)


# ===================================================================
# _validate_chroot_path_for_removal
# ===================================================================


class TestValidateChrootPathForRemoval:
    def test_root_rejected(self) -> None:
        with pytest.raises(ValidationError, match="path depth|filesystem root"):
            _validate_chroot_path_for_removal(Path("/"))

    def test_shallow_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="path depth"):
            _validate_chroot_path_for_removal(Path("/var"))

    def test_two_deep_rejected(self) -> None:
        with pytest.raises(ValidationError, match="path depth"):
            _validate_chroot_path_for_removal(Path("/tmp/chroot"))

    def test_three_deep_accepted(self) -> None:
        deep = Path("/tmp/myproject/chroot")
        _validate_chroot_path_for_removal(deep)

    def test_tmppath_accepted(self, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        _validate_chroot_path_for_removal(chroot)


# ===================================================================
# _is_mounted
# ===================================================================


class TestIsMounted:
    @patch("myproject.chroot_build.run_cmd")
    def test_returns_true_when_mounted(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert _is_mounted(tmp_path / "proc") is True

    @patch("myproject.chroot_build.run_cmd")
    def test_returns_false_when_not_mounted(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=1)
        assert _is_mounted(tmp_path / "proc") is False


# ===================================================================
# _mount_filesystems / _unmount_filesystems
# ===================================================================


class TestMountFilesystems:
    @patch("myproject.chroot_build.run_cmd")
    def test_mounts_all_expected(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        mounted: list[Path] = []
        _mount_filesystems(tmp_path, mounted)
        assert len(mounted) == len(CHROOT_MOUNT_POINTS)
        assert mock_cmd.call_count == len(CHROOT_MOUNT_POINTS)

        for i, (fs_type, source, target) in enumerate(CHROOT_MOUNT_POINTS):
            expected_path = tmp_path / target.lstrip("/")
            assert mounted[i] == expected_path
            assert expected_path.is_dir()
            cmd_args = mock_cmd.call_args_list[i][0][0]
            assert cmd_args == ["sudo", "mount", "-t", fs_type, source, str(expected_path)]

    def test_mount_points_no_devpts(self) -> None:
        """devpts should not be in CHROOT_MOUNT_POINTS (devtmpfs /dev provides it)."""
        targets = [target for _, _, target in CHROOT_MOUNT_POINTS]
        assert "/dev/pts" not in targets
        assert len(CHROOT_MOUNT_POINTS) == 3


class TestUnmountFilesystems:
    @patch("myproject.chroot_build.run_cmd")
    def test_unmounts_in_reverse_standard(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """When standard umount succeeds, no lazy fallback is needed."""
        paths = [tmp_path / "proc", tmp_path / "sys", tmp_path / "dev"]
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _unmount_filesystems(paths)
        assert mock_cmd.call_count == 3
        for i, expected in enumerate(reversed(paths)):
            cmd_args = mock_cmd.call_args_list[i][0][0]
            assert cmd_args == ["sudo", "umount", str(expected)]

    @patch("myproject.chroot_build.run_cmd")
    def test_falls_back_to_lazy(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """When standard umount fails, lazy umount is attempted."""
        paths = [tmp_path / "proc"]
        mock_cmd.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=1, stderr="busy"),
            subprocess.CompletedProcess(args=[], returncode=0),
        ]
        _unmount_filesystems(paths)
        assert mock_cmd.call_count == 2
        assert mock_cmd.call_args_list[0][0][0] == ["sudo", "umount", str(paths[0])]
        assert mock_cmd.call_args_list[1][0][0] == ["sudo", "umount", "-l", str(paths[0])]

    @patch("myproject.chroot_build.run_cmd")
    def test_continues_when_both_fail(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """Both standard and lazy unmount fail — best-effort continues."""
        paths = [tmp_path / "proc", tmp_path / "sys"]
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=1, stderr="busy")
        _unmount_filesystems(paths)
        assert mock_cmd.call_count == 4


# ===================================================================
# managed_mounts
# ===================================================================


class TestManagedMounts:
    @patch("myproject.chroot_build._unmount_filesystems")
    @patch("myproject.chroot_build._mount_filesystems")
    def test_unmounts_on_success(
        self, mock_mount: MagicMock, mock_unmount: MagicMock, tmp_path: Path
    ) -> None:
        sentinel_paths = [tmp_path / "proc"]
        mock_mount.side_effect = lambda _chroot, mounts: mounts.extend(sentinel_paths)
        with managed_mounts(tmp_path) as mounted:
            assert mounted == sentinel_paths
        mock_unmount.assert_called_once_with(sentinel_paths)

    @patch("myproject.chroot_build._unmount_filesystems")
    @patch("myproject.chroot_build._mount_filesystems")
    def test_unmounts_on_exception(
        self, mock_mount: MagicMock, mock_unmount: MagicMock, tmp_path: Path
    ) -> None:
        sentinel_paths = [tmp_path / "proc"]
        mock_mount.side_effect = lambda _chroot, mounts: mounts.extend(sentinel_paths)
        with pytest.raises(RuntimeError, match="boom"):
            with managed_mounts(tmp_path):
                raise RuntimeError("boom")
        mock_unmount.assert_called_once_with(sentinel_paths)

    @patch("myproject.chroot_build._unmount_filesystems")
    @patch("myproject.chroot_build._mount_filesystems")
    def test_cleanup_even_if_mount_partial(
        self, mock_mount: MagicMock, mock_unmount: MagicMock, tmp_path: Path
    ) -> None:
        """If _mount_filesystems raises mid-way, partial mounts are still cleaned up."""
        partial = [tmp_path / "proc"]

        def partial_mount(_chroot: Path, mounts: list[Path]) -> None:
            mounts.extend(partial)
            raise subprocess.CalledProcessError(1, "mount")

        mock_mount.side_effect = partial_mount
        with pytest.raises(subprocess.CalledProcessError):
            with managed_mounts(tmp_path):
                pass  # pragma: no cover
        # Cleanup called with the partial list — proc was mounted before failure
        mock_unmount.assert_called_once_with(partial)


# ===================================================================
# create_chroot
# ===================================================================


class TestCreateChroot:
    @patch("myproject.chroot_build.run_cmd")
    def test_calls_debootstrap(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        result = create_chroot(tmp_path, suite="jammy", mirror="http://archive.ubuntu.com/ubuntu")
        assert result == tmp_path.resolve()
        mock_cmd.assert_called_once()
        cmd = mock_cmd.call_args[0][0]
        assert cmd[0:2] == ["sudo", "debootstrap"]
        assert "--variant=minbase" in cmd
        assert "jammy" in cmd
        assert "http://archive.ubuntu.com/ubuntu" in cmd

    @patch("myproject.chroot_build.run_cmd")
    def test_defaults(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        create_chroot(tmp_path)
        cmd = mock_cmd.call_args[0][0]
        assert DEFAULT_SUITE in cmd
        assert DEFAULT_MIRROR in cmd

    def test_invalid_suite_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="invalid characters"):
            create_chroot(tmp_path, suite="jammy;evil")

    def test_invalid_mirror_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="must use http"):
            create_chroot(tmp_path, mirror="ftp://bad.example.com")

    @patch("myproject.chroot_build.run_cmd")
    def test_skips_if_already_exists(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        """Debootstrap is skipped when the chroot already has /bin/sh."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "sh").write_text("")
        result = create_chroot(tmp_path)
        assert result == tmp_path.resolve()
        mock_cmd.assert_not_called()


# ===================================================================
# install_build_deps
# ===================================================================


class TestInstallBuildDeps:
    @patch("myproject.chroot_build.run_cmd")
    def test_runs_update_and_install(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        install_build_deps(tmp_path)
        assert mock_cmd.call_count == 2
        update_cmd = mock_cmd.call_args_list[0][0][0]
        install_cmd = mock_cmd.call_args_list[1][0][0]
        assert update_cmd == [
            "sudo",
            "chroot",
            str(tmp_path.resolve()),
            "apt-get",
            "update",
            "-qq",
        ]
        assert install_cmd[:4] == [
            "sudo",
            "chroot",
            str(tmp_path.resolve()),
            "apt-get",
        ]
        assert "-y" in install_cmd
        assert "--no-install-recommends" in install_cmd
        # All build deps + extra packages should be in the command
        for pkg in CHROOT_EXTRA_PACKAGES:
            assert pkg in install_cmd


# ===================================================================
# copy_source_into_chroot
# ===================================================================


class TestCopySourceIntoChroot:
    def test_copies_source(self, tmp_path: Path) -> None:
        source = tmp_path / "linux-6.8.1"
        source.mkdir()
        (source / "Makefile").write_text("all:\n")
        chroot = tmp_path / "chroot"
        chroot.mkdir()

        result = copy_source_into_chroot(source, chroot)
        assert result == (chroot / "build" / "linux-6.8.1").resolve()
        assert (result / "Makefile").read_text() == "all:\n"

    def test_replaces_existing(self, tmp_path: Path) -> None:
        source = tmp_path / "linux-6.8.1"
        source.mkdir()
        (source / "Makefile").write_text("v2\n")
        chroot = tmp_path / "chroot"
        old_dest = chroot / "build" / "linux-6.8.1"
        old_dest.mkdir(parents=True)
        (old_dest / "Makefile").write_text("v1\n")

        result = copy_source_into_chroot(source, chroot)
        assert (result / "Makefile").read_text() == "v2\n"

    def test_source_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="does not exist"):
            copy_source_into_chroot(tmp_path / "nope", tmp_path / "chroot")


# ===================================================================
# run_chroot_build
# ===================================================================


class TestRunChrootBuild:
    @patch("myproject.kernel_builder.compute_optimal_jobs", return_value=4)
    @patch("myproject.chroot_build.run_cmd")
    def test_runs_make_in_chroot(
        self, mock_cmd: MagicMock, mock_jobs: MagicMock, tmp_path: Path
    ) -> None:
        chroot = tmp_path / "chroot"
        chroot.mkdir()
        source = chroot / "build" / "linux-6.8.1"
        source.mkdir(parents=True)

        run_chroot_build(chroot, source)
        mock_cmd.assert_called_once()
        cmd = mock_cmd.call_args[0][0]
        assert cmd[:3] == ["sudo", "chroot", str(chroot.resolve())]
        assert "env" in cmd
        assert "make" in cmd
        assert "-C" in cmd
        assert "-j4" in cmd
        assert "bindeb-pkg" in cmd
        # ccache PATH and MAKEFLAGS propagated
        assert any("ccache" in arg for arg in cmd)
        assert "MAKEFLAGS=-j4" in cmd

    @patch("myproject.chroot_build.run_cmd")
    def test_custom_jobs(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        chroot.mkdir()
        source = chroot / "build" / "linux-6.8.1"
        source.mkdir(parents=True)

        run_chroot_build(chroot, source, jobs=8)
        cmd = mock_cmd.call_args[0][0]
        assert "-j8" in cmd

    def test_source_outside_chroot_raises(self, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        chroot.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        with pytest.raises(ValidationError, match="not inside chroot"):
            run_chroot_build(chroot, outside)


# ===================================================================
# extract_artifacts
# ===================================================================


class TestExtractArtifacts:
    def test_copies_debs(self, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        build = chroot / "build"
        build.mkdir(parents=True)
        (build / "linux-image-6.8.1_amd64.deb").write_text("pkg1")
        (build / "linux-headers-6.8.1_amd64.deb").write_text("pkg2")
        (build / "linux-6.8.1").mkdir()  # not a .deb — should be skipped

        out = tmp_path / "output"
        artifacts = extract_artifacts(chroot, out)

        assert len(artifacts) == 2
        assert all(a.suffix == ".deb" for a in artifacts)
        assert all(a.parent == out.resolve() for a in artifacts)

    def test_no_debs_raises(self, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        (chroot / "build").mkdir(parents=True)

        with pytest.raises(BuildError, match="No .deb artifacts"):
            extract_artifacts(chroot, tmp_path / "output")

    def test_no_build_dir_raises(self, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        chroot.mkdir()

        with pytest.raises(BuildError, match="Build directory not found"):
            extract_artifacts(chroot, tmp_path / "output")


# ===================================================================
# teardown_chroot
# ===================================================================


class TestTeardownChroot:
    @patch("myproject.chroot_build._is_mounted", return_value=True)
    @patch("myproject.chroot_build.run_cmd")
    def test_unmounts_expected_paths(
        self, mock_cmd: MagicMock, mock_mounted: MagicMock, tmp_path: Path
    ) -> None:
        chroot = tmp_path / "chroot"
        # Create the mount point dirs so teardown finds them
        for _, _, target in CHROOT_MOUNT_POINTS:
            (chroot / target.lstrip("/")).mkdir(parents=True, exist_ok=True)

        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        teardown_chroot(chroot, remove=False)

        # Should have unmount calls for each mount point
        umount_calls = [c for c in mock_cmd.call_args_list if "umount" in c[0][0]]
        assert len(umount_calls) == len(CHROOT_MOUNT_POINTS)

    @patch("myproject.chroot_build._is_mounted", return_value=False)
    @patch("myproject.chroot_build.run_cmd")
    def test_remove_deletes_chroot(
        self, mock_cmd: MagicMock, mock_mounted: MagicMock, tmp_path: Path
    ) -> None:
        chroot = tmp_path / "chroot"
        chroot.mkdir()

        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        teardown_chroot(chroot, remove=True)

        # Last call should be sudo rm -rf
        rm_calls = [c for c in mock_cmd.call_args_list if "rm" in c[0][0]]
        assert len(rm_calls) == 1
        assert rm_calls[0][0][0] == ["sudo", "rm", "-rf", str(chroot.resolve())]

    @patch("myproject.chroot_build.run_cmd")
    def test_no_remove_preserves(self, mock_cmd: MagicMock, tmp_path: Path) -> None:
        chroot = tmp_path / "chroot"
        chroot.mkdir()
        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        teardown_chroot(chroot, remove=False)
        rm_calls = [c for c in mock_cmd.call_args_list if "rm" in c[0][0]]
        assert len(rm_calls) == 0

    @patch("myproject.chroot_build._is_mounted", return_value=True)
    @patch("myproject.chroot_build.run_cmd")
    def test_remove_refused_if_still_mounted(
        self, mock_cmd: MagicMock, mock_mounted: MagicMock, tmp_path: Path
    ) -> None:
        """rm -rf must not proceed if mount points are still active."""
        chroot = tmp_path / "chroot"
        for _, _, target in CHROOT_MOUNT_POINTS:
            (chroot / target.lstrip("/")).mkdir(parents=True, exist_ok=True)

        mock_cmd.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        with pytest.raises(BuildError, match="still active after unmount"):
            teardown_chroot(chroot, remove=True)

        rm_calls = [c for c in mock_cmd.call_args_list if "rm" in c[0][0]]
        assert len(rm_calls) == 0

    @patch("myproject.chroot_build._is_mounted", return_value=False)
    def test_remove_shallow_path_rejected(self, mock_mounted: MagicMock) -> None:
        """Shallow paths must be rejected for rm -rf."""
        with pytest.raises(ValidationError, match="path depth"):
            teardown_chroot(Path("/tmp/chroot"), remove=True)


# ===================================================================
# chroot_kernel_build (orchestrator)
# ===================================================================


class TestChrootKernelBuild:
    @patch("myproject.chroot_build.teardown_chroot")
    @patch("myproject.chroot_build.extract_artifacts")
    @patch("myproject.chroot_build.run_chroot_build")
    @patch("myproject.chroot_build.copy_source_into_chroot")
    @patch("myproject.chroot_build.install_build_deps")
    @patch("myproject.chroot_build.managed_mounts")
    @patch("myproject.chroot_build.create_chroot")
    def test_full_pipeline(
        self,
        mock_create: MagicMock,
        mock_mounts: MagicMock,
        mock_deps: MagicMock,
        mock_copy: MagicMock,
        mock_build: MagicMock,
        mock_extract: MagicMock,
        mock_teardown: MagicMock,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "linux-6.8.1"
        output = tmp_path / "output"
        chroot = tmp_path / "chroot"

        mock_create.return_value = chroot
        mock_mounts.return_value.__enter__ = MagicMock(return_value=[])
        mock_mounts.return_value.__exit__ = MagicMock(return_value=False)
        mock_copy.return_value = chroot / "build" / "linux-6.8.1"
        expected_artifacts = [output / "linux-image.deb"]
        mock_extract.return_value = expected_artifacts

        result = chroot_kernel_build(source, output, chroot_dir=chroot, suite="jammy", jobs=4)

        assert result == expected_artifacts
        mock_create.assert_called_once_with(chroot, suite="jammy", mirror=DEFAULT_MIRROR)
        mock_deps.assert_called_once_with(chroot)
        mock_copy.assert_called_once_with(source, chroot)
        mock_build.assert_called_once()
        mock_extract.assert_called_once_with(chroot, output)
        mock_teardown.assert_called_once_with(chroot, remove=True)

    @patch("myproject.chroot_build.teardown_chroot")
    @patch("myproject.chroot_build.create_chroot")
    def test_teardown_on_failure(
        self,
        mock_create: MagicMock,
        mock_teardown: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_create.side_effect = subprocess.CalledProcessError(1, "debootstrap")
        source = tmp_path / "src"
        output = tmp_path / "out"

        with pytest.raises(subprocess.CalledProcessError):
            chroot_kernel_build(source, output, chroot_dir=tmp_path / "chroot")

        # Teardown must be called even on failure
        mock_teardown.assert_called_once()

    @patch("myproject.chroot_build.teardown_chroot")
    @patch("myproject.chroot_build.extract_artifacts")
    @patch("myproject.chroot_build.run_chroot_build")
    @patch("myproject.chroot_build.copy_source_into_chroot")
    @patch("myproject.chroot_build.install_build_deps")
    @patch("myproject.chroot_build.managed_mounts")
    @patch("myproject.chroot_build.create_chroot")
    def test_default_chroot_dir(
        self,
        mock_create: MagicMock,
        mock_mounts: MagicMock,
        mock_deps: MagicMock,
        mock_copy: MagicMock,
        mock_build: MagicMock,
        mock_extract: MagicMock,
        mock_teardown: MagicMock,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "linux-6.8.1"
        output = tmp_path / "output"

        mock_create.return_value = output / ".chroot"
        mock_mounts.return_value.__enter__ = MagicMock(return_value=[])
        mock_mounts.return_value.__exit__ = MagicMock(return_value=False)
        mock_copy.return_value = output / ".chroot" / "build" / "linux-6.8.1"
        mock_extract.return_value = []

        chroot_kernel_build(source, output)

        # Should use output/.chroot as default
        mock_create.assert_called_once()
        create_chroot_arg = mock_create.call_args[0][0]
        assert create_chroot_arg == output / ".chroot"

    @patch("myproject.chroot_build.teardown_chroot")
    @patch("myproject.chroot_build.extract_artifacts")
    @patch("myproject.chroot_build.run_chroot_build")
    @patch("myproject.chroot_build.copy_source_into_chroot")
    @patch("myproject.chroot_build.install_build_deps")
    @patch("myproject.chroot_build.managed_mounts")
    @patch("myproject.chroot_build.create_chroot")
    def test_no_cleanup(
        self,
        mock_create: MagicMock,
        mock_mounts: MagicMock,
        mock_deps: MagicMock,
        mock_copy: MagicMock,
        mock_build: MagicMock,
        mock_extract: MagicMock,
        mock_teardown: MagicMock,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "linux-6.8.1"
        output = tmp_path / "output"

        mock_create.return_value = output / ".chroot"
        mock_mounts.return_value.__enter__ = MagicMock(return_value=[])
        mock_mounts.return_value.__exit__ = MagicMock(return_value=False)
        mock_copy.return_value = output / ".chroot" / "build" / "linux-6.8.1"
        mock_extract.return_value = []

        chroot_kernel_build(source, output, cleanup=False)
        mock_teardown.assert_called_once_with(output / ".chroot", remove=False)
