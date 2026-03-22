# Linux Kernel Builder

A Python CLI tool for downloading, configuring, compiling, and installing Linux kernels from source on Debian/Ubuntu systems.

All user interaction is driven by **numbered menus** — no flags to memorize. Build output streams to the terminal in real time, or you can redirect it to a log file.

---

## What It Does

| Feature | Details |
|---------|---------|
| **Mainline kernel** | Download and build any version from kernel.org, or auto-fetch the latest stable |
| **Rebuild running kernel** | Detect your running kernel, pull its config from `/boot` or `/proc/config.gz`, rebuild from mainline source |
| **Ubuntu kernel** | Fetch Ubuntu-patched source via `apt-get source` and build it |
| **Install or package** | `make install` + `make modules_install`, or generate `.deb` packages with `make bindeb-pkg` |
| **Input validation** | Strict `[0-9a-zA-Z.-]` whitelist on user input; relaxed `[0-9a-zA-Z.-+_]` for system-derived kernel versions (`uname -r`) — no injection possible |
| **Locale** | Forces `en_US.UTF-8` to avoid encoding issues during builds |
| **flash-kernel** | Checks for `flash-kernel` at startup (needed on ARM/embedded) |
| **Kernel signing** | Optional — generate a signing key pair or use your own, signs via in-tree `scripts/sign-file` |
| **Ubuntu cert fix** | Automatically disables `CONFIG_SYSTEM_TRUSTED_KEYS` and `CONFIG_SYSTEM_REVOCATION_KEYS` when Canonical's internal `.pem` files are missing — fixes the most common Ubuntu kernel build failure |
| **Dependency auto-fix** | If compilation fails due to missing packages, it pauses, installs them via `apt-get`, and retries (up to 3 times) |
| **Parallel builds** | Auto-calculates `make -j` based on `min(cpu_count, available_ram_gb * 2)` to prevent OOM kills |
| **ccache** | Auto-detected — if installed, rebuilds go from hours to minutes |
| **GPG verification** | Auto-imports kernel.org signing keys from `keyserver.ubuntu.com`, then verifies tarball signatures — no manual key setup needed |
| **Module signing fix** | Automatically disables `CONFIG_MODULE_SIG` and `CONFIG_MODULE_SIG_FORCE` when the signing key is cleared — prevents `sign-file` SSL errors during `.deb` packaging |
| **Safe extraction** | Tarball extraction validates every member path to prevent directory traversal attacks |
| **SSRF protection** | Downloads are restricted to `kernel.org` domains only |

---

## Requirements

- **Linux** (Debian/Ubuntu) — uses `apt-get`, `make`, `wget`, `dpkg`, `uname`, `sudo`
- **Python 3.10+** (stdlib only — no pip packages required)
- **Root access** (via `sudo`) for installing deps and the final `make install`

Build dependencies (`build-essential`, `flex`, `bison`, `libssl-dev`, `libelf-dev`, etc.) are **installed automatically** if missing.

---

## Quick Start

```bash
# 1. Install Python and Git
sudo apt update && sudo apt install -y python3 git

# 2. Clone and run
git clone https://github.com/DBLTIME4CODE/Repo4FriendLinuxTool.git
cd Repo4FriendLinuxTool
chmod +x run.sh
./run.sh
```

There is nothing to `pip install`. The tool uses only the Python standard library.

You'll see:

```
============================================================
  Linux Kernel Builder
============================================================
  1) Build mainline kernel (specific version)
  2) Build latest stable kernel from kernel.org
  3) Rebuild running kernel from source
  4) Build Ubuntu-patched kernel
  5) Exit

Select an option:
```

---

## Walkthrough: Build the Latest Stable Kernel

```
Select an option: 2
Latest stable kernel: 6.12.3
Build kernel 6.12.3? [y/n]: y
Build directory [/home/user/kernel-build]:        ← Enter for default
Redirect build output to a log file? [y/n]: n     ← stream to terminal

Installing packages: build-essential, flex, bison, libssl-dev ...

Downloading https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.3.tar.xz
Importing kernel.org signing keys from hkps://keyserver.ubuntu.com
GPG signature verified for linux-6.12.3.tar
Extracting linux-6.12.3.tar.xz

============================================================
  Kernel configuration
============================================================
  1) Use running kernel's config (olddefconfig)
  2) Use default config (defconfig)
  3) Run menuconfig (interactive)

Select an option: 1                               ← copies your running config

Building kernel with 8 parallel jobs ...
  CC      init/main.o
  CC      init/version.o
  ...                                             ← full build output streams here

============================================================
  Build output
============================================================
  1) Compile kernel only (make)
  2) Generate .deb packages (make bindeb-pkg)

Select an option: 2                               ← generates installable .deb files

Sign the kernel? [y/n]: n
Done!
```

The `.deb` files land in the build directory. Install with:

```bash
sudo dpkg -i ~/kernel-build/linux-image-*.deb ~/kernel-build/linux-headers-*.deb
sudo reboot
```

---

## Walkthrough: Rebuild Your Running Kernel

```
Select an option: 3
```

This automatically:
1. Reads your running version via `uname -r` (e.g. `6.5.0-44-generic`)
2. Strips the Ubuntu suffix to get the mainline base (`6.5.0`)
3. Downloads that version from kernel.org
4. Copies your current `/boot/config-*` as the build config
5. Runs `make olddefconfig` to update it for the new source
6. Builds with max parallelism

---

## Walkthrough: Build an Ubuntu Kernel

```
Select an option: 4
```

This runs `apt-get source linux-image-$(uname -r)` to fetch the exact Ubuntu-patched source for your running kernel, applies your config, and builds it.

**Note:** Requires `deb-src` lines in `/etc/apt/sources.list`. If missing, add them:

```bash
sudo sed -i 's/^# deb-src/deb-src/' /etc/apt/sources.list
sudo apt-get update
```

---

## Kernel Signing

When prompted "Sign the kernel?", choosing `y` gives you two options:

1. **Generate a new key pair** — creates `kernel-signing-key.pem` (private, `chmod 600`) and `kernel-signing-cert.pem` using OpenSSL RSA-4096
2. **Use existing keys** — point it to your own `.pem` files

Signing uses the kernel tree's built-in `scripts/sign-file` tool with SHA-512.

---

## Log File Mode

If you choose to redirect output to a log file, you'll see status messages on screen while the full `make` output goes to the file:

```
Redirect build output to a log file? [y/n]: y
Log file path [/home/user/kernel-build/build.log]:
```

Tail the log in another terminal:

```bash
tail -f ~/kernel-build/build.log
```

---

## What Happens When a Build Fails

If `make` fails (missing header, missing tool, etc.), the tool:

1. **Pauses** compilation
2. Runs `sudo apt-get install` for the full build dependency list
3. **Retries** `make` from where it left off
4. Repeats up to **3 times** before giving up

This covers the common case of "I forgot to install `libssl-dev`" without you having to start over.

---

## Programmatic Usage

Skip the menus and call functions directly:

```python
from pathlib import Path
from myproject.kernel_builder import (
    download_kernel,
    build_kernel,
    install_kernel,
    fetch_latest_version,
    build_deb_package,
    configure_kernel,
    extract_running_config,
)

# Build latest stable and generate .deb packages
version = fetch_latest_version()                     # "6.12.3"
source = download_kernel(version, Path("/tmp/kbuild"))
config = extract_running_config(source)
configure_kernel(source, config)
build_deb_package(source, jobs=8)
```

When using as a library, set `PYTHONPATH=src` or install with `pip install -e .`.

---

## File Layout

```
run.sh                       # Entry point — just run this
pyproject.toml               # Project metadata (no runtime deps)
src/myproject/
├── kernel_builder.py        # Core engine — validation, download,
│                            #   build, install, signing
├── kernel_cli.py            # Interactive numbered-menu CLI
├── chroot_build.py          # Clean chroot compilation module
└── __init__.py

tests/
├── test_kernel_builder.py   # 125 unit tests (kernel builder)
└── test_chroot_build.py     # 62 unit tests (chroot build)
```

---

## Clean Chroot Compilation

The `chroot_build` module provides an **isolated build environment** using `debootstrap`. This ensures your host system is never contaminated by build dependencies, and every build is reproducible from scratch.

### Why Use a Chroot?

| Problem | Solution |
|---------|----------|
| Build deps pollute your host system | All packages install inside a disposable chroot |
| "Works on my machine" — host-specific libs leak in | Chroot starts from a minimal base image |
| Stale object files from previous builds | Fresh chroot = clean slate every time |
| Debugging "did I break my system?" after a bad build | Host is untouched — just delete the chroot |

### How It Works

The `chroot_kernel_build()` orchestrator runs this pipeline:

```
1. debootstrap        Create minimal Debian/Ubuntu chroot
         ↓
2. mount /proc,       Mount virtual filesystems for build
   /sys, /dev         compatibility
         ↓
3. apt-get install    Install build-essential, flex, bison,
                      libssl-dev, etc. inside the chroot
         ↓
4. copytree           Copy your kernel source tree into
                      <chroot>/build/
         ↓
5. chroot make        Run `make -C /build/linux-X.Y.Z
   bindeb-pkg         -jN bindeb-pkg` inside the chroot
         ↓
6. copy .deb          Extract the resulting .deb packages
   artifacts          to your output directory
         ↓
7. teardown           Unmount filesystems, optionally
                      delete the chroot
```

### Quick Start (Programmatic)

```python
from pathlib import Path
from myproject.chroot_build import chroot_kernel_build

# Build kernel 6.8.1 in a clean Debian bookworm chroot
artifacts = chroot_kernel_build(
    source_dir=Path("/home/user/kernel-build/linux-6.8.1"),
    output_dir=Path("/home/user/kernel-debs"),
    suite="bookworm",                    # or "jammy" for Ubuntu
    mirror="http://deb.debian.org/debian",
    jobs=8,
    cleanup=True,                        # delete chroot when done
)

# artifacts = [Path("/home/user/kernel-debs/linux-image-6.8.1_amd64.deb"), ...]
for deb in artifacts:
    print(f"Built: {deb}")
```

### Step-by-Step (Individual Functions)

```python
from pathlib import Path
from myproject.chroot_build import (
    create_chroot,
    install_build_deps,
    copy_source_into_chroot,
    run_chroot_build,
    extract_artifacts,
    teardown_chroot,
    managed_mounts,
)

chroot = Path("/tmp/myproject/chroot")

# 1. Create chroot
create_chroot(chroot, suite="bookworm")

# 2. Mount + build inside context manager (guarantees cleanup)
with managed_mounts(chroot):
    install_build_deps(chroot)
    src = copy_source_into_chroot(Path("~/linux-6.8.1"), chroot)
    run_chroot_build(chroot, src, jobs=4)
    debs = extract_artifacts(chroot, Path("~/output"))

# 3. Cleanup
teardown_chroot(chroot, remove=True)
```

### Safety Features

| Feature | Detail |
|---------|--------|
| **No `shell=True`** | Every subprocess call uses list-form arguments — zero injection surface |
| **Standard unmount first** | Tries `umount` before falling back to `umount -l` (lazy) — prevents rm-rf race with still-mounted host filesystems |
| **Mount verification before rm** | Checks `mountpoint -q` on every mount point before allowing `rm -rf` — refuses to delete if any mount is still active |
| **Path depth guard** | Will not `rm -rf` paths less than 3 levels deep (blocks accidental `rm -rf /var`) |
| **Glob validation** | Rejects recursive `**` patterns and shell metacharacters in artifact search |
| **Input validation** | Suite names and mirror URLs are validated before reaching `sudo` commands |
| **Context manager cleanup** | `managed_mounts()` guarantees unmount even if the build crashes mid-way |

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `suite` | `"bookworm"` | Debian/Ubuntu release codename |
| `mirror` | `"http://deb.debian.org/debian"` | APT mirror URL (http or https) |
| `jobs` | Auto-detected | Parallel make jobs (`min(cpus, ram_gb * 2)`) |
| `cleanup` | `True` | Delete chroot after build |
| `chroot_dir` | `output_dir/.chroot` | Where to create the chroot |

### Requirements

- **Linux** (Debian/Ubuntu) — needs `debootstrap`, `sudo`, `mount`, `mountpoint`
- **Python 3.10+**
- **Root access** via `sudo`

Install `debootstrap` if not present:

```bash
sudo apt-get install -y debootstrap
```

---

## Running Tests

```bash
sudo apt install -y python3-pip
pip install pytest ruff mypy
PYTHONPATH=src pytest -q
```

All tests pass. They mock every subprocess call, so they run on Linux, macOS, and Windows without needing root or a network.

---

## License

Do whatever you want with it.
