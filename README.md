# llmfit

Unofficial PyPI distribution of [llmfit](https://github.com/AlexsJones/llmfit) — the LLM model management CLI.

This package downloads pre-built binaries from the upstream GitHub releases and
repackages them as Python wheels so you can install `llmfit` with pip or uv
without a Rust toolchain.

## Installation

```bash
pip install llmfit
# or
uv add llmfit
```

After installation the `llmfit` command is available on your PATH.

```bash
llmfit --help
```

## Supported platforms

| Platform | Architecture | Notes |
|---|---|---|
| Linux (glibc) | x86_64 | Requires glibc ≥ 2.17 |
| Linux (glibc) | aarch64 | Requires glibc ≥ 2.17 |
| macOS | x86_64 (Intel) | Requires macOS ≥ 10.15 |
| macOS | arm64 (Apple Silicon) | Requires macOS ≥ 11.0 |
| Windows | x86_64 | |
| Windows | ARM64 | |

### Alpine / musl Linux

`pip install llmfit` selects the glibc wheel on Linux; Alpine uses musl and
the glibc binary will not run. Install the musl wheel directly instead:

```bash
# x86_64
pip install llmfit-x86-64-unknown-linux-musl

# aarch64
pip install llmfit-aarch64-unknown-linux-musl
```

## Version correspondence

The version of this package always matches the upstream llmfit release tag
(with the leading `v` stripped). `llmfit==0.8.6` contains `v0.8.6` of the
upstream binary.

## About this package

This is an unofficial redistribution. The `llmfit` binary is the work of
[Alex Jones](https://github.com/AlexsJones) and contributors, released under
the MIT License. See [LICENSE](LICENSE) for details.

Source for this packaging wrapper: <https://github.com/JEHoctor/llmfit-pypi>

---

## For maintainers of this repository

### How it works

1. A nightly GitHub Actions workflow (`check_upstream.yml`) compares the
   latest upstream tag with the published PyPI version.
2. If they differ, it triggers `build_and_publish.yml` with the new tag.
3. `build_and_publish.yml` calls `build_wheels.py`, which downloads each
   platform archive from GitHub Releases, verifies its SHA256 checksum,
   extracts the binary, and constructs a platform wheel. It also builds the
   `llmfit` meta-package wheel.
4. All wheels are published to PyPI via OIDC Trusted Publisher (no API tokens
   stored in repository secrets).

You can also trigger a build manually from the Actions tab, providing the
version tag (e.g. `v0.8.6`).

### One-time setup (required before first publish)

These steps cannot be automated and must be done once by the repository owner.

**1. Create PyPI projects**

Register the following package names on PyPI (pypi.org) under your account:

- `llmfit`
- `llmfit-x86-64-unknown-linux-gnu`
- `llmfit-aarch64-unknown-linux-gnu`
- `llmfit-x86-64-unknown-linux-musl`
- `llmfit-aarch64-unknown-linux-musl`
- `llmfit-x86-64-apple-darwin`
- `llmfit-aarch64-apple-darwin`
- `llmfit-x86-64-pc-windows-msvc`
- `llmfit-aarch64-pc-windows-msvc`

You can create a project by uploading a minimal first release (e.g. via
`python -m twine upload`) or by registering through the PyPI web UI.

**2. Configure PyPI Trusted Publisher for each package**

For each of the 9 PyPI projects above, go to the project's settings page on
pypi.org and add a Trusted Publisher with these values:

| Field | Value |
|---|---|
| Owner | `JEHoctor` (your GitHub username) |
| Repository | `llmfit-pypi` |
| Workflow name | `build_and_publish.yml` |
| Environment name | `pypi` |

This enables OIDC authentication so the workflow can publish without storing
API tokens.

**3. Set GitHub Actions workflow permissions**

In this repository go to **Settings → Actions → General → Workflow permissions**
and select **Read and write permissions**. This allows `check_upstream.yml` to
trigger `build_and_publish.yml` via `workflow_dispatch`.

Also create a **GitHub Actions environment** named `pypi` (Settings →
Environments) and optionally add a protection rule requiring manual approval
before publishing.
