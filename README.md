# llmfit via PyPI

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

You can also use this package to install and update `llmfit` via uv tool:

```bash
uv tool install -U llmfit
```

## Supported platforms

See [Rust platform support](https://doc.rust-lang.org/nightly/rustc/platform-support.html) for more information.
Refer to the the [upstream llmfit project](https://github.com/AlexsJones/llmserve?tab=readme-ov-file#llmserve) for authoritative requirements.

| Platform | Architecture | Requirements |
|---|---|---|
| Linux (glibc) | x86_64 | kernel ≥ 3.2, glibc ≥ 2.17 |
| Linux (glibc) | aarch64 | kernel ≥ 4.1, glibc ≥ 2.17 |
| Linux (musl) | x86_64 | musl ≥ 1.2.5 |
| Linux (musl) | aarch64 | musl ≥ 1.2.5 |
| macOS | x86_64 (Intel) | macOS ≥ 10.12 |
| macOS | arm64 (Apple Silicon) | macOS ≥ 11.0 |
| Windows | x86_64 | Windows 10+ or Windows Server 2016+ |
| Windows | ARM64 | |

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
   extracts the binary, and constructs a platform-tagged wheel for the `llmfit`
   package.
4. All wheels are published to PyPI via OIDC Trusted Publisher (no API tokens
   stored in repository secrets).

You can also trigger a build manually from the Actions tab, providing the
version tag (e.g. `v0.8.6`).
