# Code Walkthrough — How the Kernel Builder Works

This document explains every part of the code in plain English. You don't need to be a programmer to follow along — I'll explain what each piece does and why it's there.

---

## The Big Picture

The tool is split into **two files**:

| File | Role | Analogy |
|------|------|---------|
| `kernel_builder.py` | **The engine** — does all the real work | The car engine, transmission, brakes |
| `kernel_cli.py` | **The dashboard** — talks to the user | The steering wheel, pedals, gauges |

The CLI file handles menus and user input, then calls functions from the engine to actually do things. This separation means you could swap out the menu interface without touching any of the build logic.

---

## Part 1: kernel_builder.py (The Engine)

### 1.1 — Imports

All built-in Python libraries — no extra packages needed:

| Import | Why we need it |
|--------|---------------|
| `gzip` | Decompress `/proc/config.gz` (compressed kernel config) |
| `hashlib` | Calculate SHA-256 checksums to verify downloads aren't corrupted |
| `json` | Parse the kernel.org API response |
| `logging` | Print status messages with severity levels (INFO, WARNING, ERROR) |
| `os` | Read environment variables, get CPU count, file permissions |
| `re` | Regular expressions for input validation |
| `shutil` | Copy files, find programs on PATH (like `ccache`) |
| `stat` | Set file permissions (signing key gets `chmod 600`) |
| `subprocess` | Run Linux commands (`make`, `wget`, `apt-get`) from Python |
| `sys` | Access `sys.stdout` for streaming build output |
| `tarfile` | Safely extract `.tar.xz` kernel source archives |
| `Path` | Object-oriented file paths — cleaner than string manipulation |
| `urlopen` | Make HTTP requests (fetch latest kernel version from kernel.org) |

---

### 1.2 — Constants

- **`MAX_INPUT_LENGTH = 256`** — No user input longer than 256 chars
- **`MAX_RETRIES = 3`** — If the build fails, retry up to 3 times
- **`SAFE_INPUT_RE`** — A pattern that says "only allow letters, numbers, dots, and dashes"
- **`BUILD_DEPS`** — The list of packages needed to compile a kernel (like a recipe's ingredient list)
- **`ALLOWED_DOWNLOAD_DOMAINS`** — Only `kernel.org` domains are permitted for downloads. Security measure against SSRF.

---

### 1.3 — Custom Exceptions

```python
class ValidationError(ValueError): ...
class BuildError(RuntimeError): ...
```

Instead of generic "something went wrong," these say specifically "user typed something invalid" or "the compilation failed." The code can catch each one separately and respond differently.

---

### 1.4 — Input Validation (THE most important security function)

```python
def validate_input(value, label="input"):
```

Every piece of user input passes through this before being used anywhere. It checks:

1. **Not empty** — can't submit blank
2. **No null bytes** — invisible characters hackers use to confuse programs
3. **Not too long** — max 256 characters
4. **Only safe characters** — must match `[0-9a-zA-Z.-]`

**Why this matters:** The tool runs `sudo` commands. If someone typed `6.8; rm -rf /` as a version and it wasn't validated, it could delete the entire filesystem. The whitelist makes that impossible.

`validate_url_domain()` does the same for URLs — only `https://` to `kernel.org` is allowed.

---

### 1.5 — Locale Enforcement

```python
def enforce_locale():
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"
```

Forces English UTF-8. Build tools behave differently in different languages — forcing English makes error messages predictable for the auto-retry logic.

---

### 1.6 — Running Commands

```python
def run_cmd(cmd: list[str], ...):
    return subprocess.run(cmd, ...)
```

The single function that runs ALL external commands. **Key:** `cmd` is always a **list** (`["wget", "-q", url]`), never a string. List form prevents shell injection attacks.

`_run_streaming()` is the same but reads output **line by line** — used during compilation so you see progress in real time instead of a blank screen for 2 hours.

---

### 1.7 — System Detection

- **`get_running_kernel()`** — Runs `uname -r`, returns e.g. `"6.5.0-44-generic"`
- **`check_flash_kernel()`** — Checks if `flash-kernel` is installed (needed on ARM/Raspberry Pi)
- **`compute_optimal_jobs()`** — Calculates `min(cpu_count, ram_gb * 2)`. If you have 16 cores but 2 GB RAM, it limits to 4 jobs to prevent out-of-memory crashes

---

### 1.8 — Config Extraction

```python
def extract_running_config(dest_dir):
```

The kernel has thousands of options (WiFi? Bluetooth? Which filesystem drivers?). This function finds your current kernel's config from `/boot/config-*` or `/proc/config.gz` and copies it so the new build starts with the same settings.

---

### 1.9 — Downloading (security-hardened)

The full download flow:

1. `validate_input(version)` — Is the version string safe?
2. `_kernel_url(version)` — Build the URL
3. `validate_url_domain(url)` — Does it point to kernel.org?
4. `wget` — Download the ~150 MB tarball
5. `verify_gpg_signature()` — Check cryptographic signature (if available)
6. `safe_extract_tarball()` — Extract, checking every file path for traversal attacks

**`safe_extract_tarball()`** is critical — a malicious tarball could contain `../../../etc/passwd` that writes outside the destination. This function checks every member and blocks that.

---

### 1.10 — Building (the core)

```python
def build_kernel(source_dir, jobs=None, log_file=None):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            run_cmd(["make", f"-j{jobs}"], ...)
            return                              # Success!
        except subprocess.CalledProcessError:
            if attempt == MAX_RETRIES:
                raise BuildError(...)           # Give up
            ensure_build_deps()                 # Install packages, retry
```

**The retry loop:** Run `make`. If it fails, install all build dependencies, retry. Up to 3 times. This handles "forgot to install `libssl-dev`" automatically.

**ccache:** If installed, the tool puts it in front of the compiler. Repeat builds go from hours to minutes. Detected automatically — no config needed.

---

### 1.11 — Installation

```python
run_cmd(["sudo", "make", "modules_install"])   # Copy drivers to /lib/modules/
run_cmd(["sudo", "make", "install"])            # Copy kernel to /boot/, update GRUB
```

Both need `sudo`. After this + reboot, you're on your new kernel.

---

### 1.12 — Kernel Signing

Generates an RSA-4096 key pair with OpenSSL. Private key gets `chmod 600` (owner-only). Signs the kernel with the in-tree `scripts/sign-file` using SHA-512.

**Why?** Secure Boot only loads signed modules. Without this, a custom kernel's modules get rejected.

---

### 1.13 — Menu Helpers

- `numbered_menu()` — Shows options numbered 1, 2, 3... keeps asking until valid
- `prompt_yes_no()` — Asks y/n questions
- `setup_logging()` — Controls output: screen, file, or both

---

## Part 2: kernel_cli.py (The Dashboard)

This file is just the user interface. It imports everything from `kernel_builder.py` and orchestrates the flow:

1. Set up logging and locale
2. Check for flash-kernel
3. Show main menu (5 options)
4. Based on choice: get source → configure → build → optionally install/sign

Each menu option follows the same pattern — the only difference is where the source code comes from.

---

## Part 3: Full Flow Diagram

When you pick "Build latest stable kernel":

```
User picks option 2
  |
  +-- fetch_latest_version()          <-- asks kernel.org "what's latest?"
  |       returns "6.12.3"
  |
  +-- download_kernel("6.12.3")
  |       +-- validate input           <-- safe characters only
  |       +-- build URL                <-- cdn.kernel.org/pub/linux/...
  |       +-- validate domain          <-- is it kernel.org? yes
  |       +-- wget download            <-- ~150 MB tarball
  |       +-- GPG signature check      <-- is it authentic?
  |       +-- safe extract             <-- no path traversal
  |
  +-- configure kernel
  |       +-- copy running config      <-- from /boot/config-*
  |       +-- make olddefconfig        <-- update for new source
  |       +-- sanitize cert configs    <-- remove missing Canonical .pem refs
  |
  +-- build
  |       +-- compute jobs             <-- min(cpus, ram*2)
  |       +-- make -j8 bindeb-pkg      <-- THE BIG BUILD
  |       +-- if fails: install deps, retry (up to 3x)
  |
  +-- optionally sign with generated key
  +-- done!
```

---

## Part 4: Security Summary

| Threat | Protection |
|--------|-----------|
| Command injection (`; rm -rf /`) | Whitelist: only `[0-9a-zA-Z.-]` for user input; `[0-9a-zA-Z.-+_]` for system versions |
| Shell injection | `subprocess.run()` list form, never `shell=True` |
| Download from bad server | Domain allowlist: only `kernel.org` |
| HTTP downgrade | Must be `https://` |
| Corrupted download | SHA-256 checksum |
| Tampered download | GPG signature verification |
| Malicious tarball paths | Every member validated before extraction |
| Symlink escape in tarball | Symlink targets checked |
| Null byte injection | Explicit `\x00` check |
| Oversized input | Max 256 characters |
| Signing key exposure | `chmod 600` on private key |
| Ubuntu cert build failure | Auto-clears `CONFIG_SYSTEM_TRUSTED_KEYS` / `CONFIG_SYSTEM_REVOCATION_KEYS` when `.pem` files missing |

---

## Part 5: The Tests

79 → **111** tests that never run real commands. They use Python's `mock` to fake subprocess results:

```python
@patch("myproject.kernel_builder.run_cmd")
def test_installed(self, mock_cmd):
    mock_cmd.return_value = CompletedProcess(returncode=0)
    assert check_flash_kernel() is True
```

Translation: "Pretend `dpkg -s flash-kernel` returned success. Verify the function returns True."

That's why tests run on any OS including Windows.

### Running the tests

```bash
# One-time setup
sudo apt install -y python3-pip python3-venv
python3 -m venv .venv && source .venv/bin/activate
pip install pytest

# Run
pytest -q          # all 111 tests — no root, no network
```

No `pip install -e .` is required — `pyproject.toml` sets
`pythonpath = ["src"]` so pytest finds the package automatically.

---

## Glossary

| Term | Meaning |
|------|---------|
| **kernel** | Core of an OS — manages hardware, memory, processes |
| **tarball** | `.tar.xz` archive (like a zip file for Linux) |
| **make** | Build tool that compiles source code |
| **make -j8** | Compile 8 files in parallel |
| **olddefconfig** | "Use my existing config, default any new options" |
| **defconfig** | "Use the kernel's recommended defaults" |
| **menuconfig** | "Interactive menu to pick kernel options" |
| **bindeb-pkg** | "Build kernel and package as installable .deb files" |
| **ccache** | Compiler cache — speeds up repeat builds dramatically |
| **GPG** | Cryptographic signature tool |
| **SHA-256** | Hash that creates a unique file fingerprint |
| **SSRF** | Tricking a program into calling unintended servers |
| **OOM** | Out of memory crash |
| **Secure Boot** | Only loads signed OS code |
