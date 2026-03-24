# ARCHIE Distribution — Implementation Plan (Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package ARCHIE Code CLI for distribution — pip installable Python engine, cross-compiled Go binary, bootstrap install script, and GitHub Actions CI/CD.

**Architecture:** Two packages: `archie-engine` (pip/PyPI) and `archie-code` (Go binary). Bootstrap script installs engine via pip, downloads TUI binary from GitHub releases. CI/CD builds both on tag push.

**Tech Stack:** setuptools, GitHub Actions, Go cross-compilation, shell scripting.

**Depends on:** Plan 2-6 (complete).

**Rollback:** Additive. Revert commits.

---

## Task Overview (6 Tasks)

| # | Task | Scope |
|---|------|-------|
| 7.1 | Python package setup | pyproject.toml polish, setup.cfg, MANIFEST.in |
| 7.2 | Go cross-compilation | Makefile for linux/mac/windows x amd64/arm64 |
| 7.3 | Bootstrap install script | curl one-liner that installs both components |
| 7.4 | GitHub Actions — Python | Build + test on push/PR |
| 7.5 | GitHub Actions — Go + Release | Cross-compile + release on tag |
| 7.6 | Push and close out | Push, log decision |

---

### Task 7.1: Python package setup

**Files:**
- Modify: `archie_engine/pyproject.toml` — add classifiers, URLs, readme
- Create: `archie_engine/MANIFEST.in` — include community skills
- Create: `archie_engine/setup.cfg` — flake8 config

- [ ] **Step 1: Polish pyproject.toml**

Read existing, update to include:
- Project URLs (homepage, repository)
- Classifiers
- License
- Include package data (community skills .md files)
- Add `pyyaml` to dependencies (needed for skill parsing)

- [ ] **Step 2: Create MANIFEST.in**

```
include archie_engine/skills/community/*.md
```

- [ ] **Step 3: Verify pip install works locally**

```bash
cd /mnt/archie_brain && pip install --break-system-packages -e ./archie_engine
archie-engine --help 2>&1 || python -m archie_engine
```

- [ ] **Step 4: Verify tests still pass**

```bash
python -m pytest archie_engine/tests/ -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add archie_engine/ && git commit -m "feat(dist): polish Python package for pip distribution"
```

---

### Task 7.2: Go cross-compilation Makefile

**Files:**
- Create: `archie-tui/Makefile`

- [ ] **Step 1: Write Makefile**

```makefile
VERSION ?= 0.1.0
BINARY_NAME = archie-code
GO = go
GOFLAGS = -ldflags "-s -w -X main.version=$(VERSION)"

# Build targets
PLATFORMS = linux/amd64 linux/arm64 darwin/amd64 darwin/arm64 windows/amd64

.PHONY: build clean all

build:
	$(GO) build $(GOFLAGS) -o $(BINARY_NAME) .

all: clean
	@for platform in $(PLATFORMS); do \
		os=$$(echo $$platform | cut -d/ -f1); \
		arch=$$(echo $$platform | cut -d/ -f2); \
		ext=""; \
		if [ "$$os" = "windows" ]; then ext=".exe"; fi; \
		output="dist/$(BINARY_NAME)-$$os-$$arch$$ext"; \
		echo "Building $$output..."; \
		GOOS=$$os GOARCH=$$arch $(GO) build $(GOFLAGS) -o $$output .; \
	done

clean:
	rm -f $(BINARY_NAME)
	rm -rf dist/
```

- [ ] **Step 2: Test local build**

```bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/archie_brain/archie-tui && make build && ./archie-code --version
```

- [ ] **Step 3: Test cross-compile (one target)**

```bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/archie_brain/archie-tui && GOOS=linux GOARCH=arm64 go build -ldflags "-s -w" -o /tmp/archie-code-arm64 . && echo "Cross-compile OK" && rm /tmp/archie-code-arm64
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/Makefile && git commit -m "feat(dist): Go cross-compilation Makefile for 5 platforms"
```

---

### Task 7.3: Bootstrap install script

**Files:**
- Create: `install.sh`

- [ ] **Step 1: Write install.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-latest}"
REPO="KytranKatarn/archie-code"
INSTALL_DIR="${HOME}/.local/bin"

echo "╔══════════════════════════════════════╗"
echo "║    A.R.C.H.I.E. Code CLI Installer  ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Detect OS and architecture
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    arm64)   ARCH="arm64" ;;
    *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

echo "Detected: $OS/$ARCH"

# Step 1: Install Python engine
echo ""
echo "Installing ARCHIE Engine (Python)..."
if command -v pip3 &>/dev/null; then
    pip3 install archie-engine 2>/dev/null || pip3 install --user archie-engine
elif command -v pip &>/dev/null; then
    pip install archie-engine 2>/dev/null || pip install --user archie-engine
else
    echo "WARNING: pip not found. Install Python 3.11+ and pip, then run:"
    echo "  pip install archie-engine"
fi

# Step 2: Download Go TUI binary
echo ""
echo "Downloading ARCHIE Code TUI..."
mkdir -p "$INSTALL_DIR"

if [ "$VERSION" = "latest" ]; then
    DOWNLOAD_URL="https://github.com/$REPO/releases/latest/download/archie-code-$OS-$ARCH"
else
    DOWNLOAD_URL="https://github.com/$REPO/releases/download/v$VERSION/archie-code-$OS-$ARCH"
fi

if [ "$OS" = "windows" ]; then
    DOWNLOAD_URL="${DOWNLOAD_URL}.exe"
fi

if command -v curl &>/dev/null; then
    curl -sL "$DOWNLOAD_URL" -o "$INSTALL_DIR/archie-code" || {
        echo "Download failed. Binary not yet published — build from source:"
        echo "  cd archie-tui && go build -o archie-code ."
    }
elif command -v wget &>/dev/null; then
    wget -q "$DOWNLOAD_URL" -O "$INSTALL_DIR/archie-code" || {
        echo "Download failed."
    }
fi

chmod +x "$INSTALL_DIR/archie-code" 2>/dev/null || true

# Step 3: Verify
echo ""
echo "Installation complete!"
echo ""
echo "Usage:"
echo "  1. Start the engine:  python -m archie_engine"
echo "  2. Launch the TUI:    archie-code"
echo ""
echo "Make sure $INSTALL_DIR is in your PATH."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x install.sh
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add install.sh && git commit -m "feat(dist): bootstrap install script for curl one-liner"
```

---

### Task 7.4: GitHub Actions — Python CI

**Files:**
- Create: `.github/workflows/python-ci.yml`

- [ ] **Step 1: Write workflow**

```yaml
name: Python CI

on:
  push:
    paths: ['archie_engine/**']
  pull_request:
    paths: ['archie_engine/**']

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.12']

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install aiosqlite websockets aiohttp pyyaml pytest pytest-asyncio

      - name: Run tests
        run: |
          python -m pytest archie_engine/tests/ -v --tb=short
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain && mkdir -p .github/workflows && git add .github/workflows/python-ci.yml && git commit -m "ci: Python CI workflow — test on push/PR"
```

---

### Task 7.5: GitHub Actions — Go Build + Release

**Files:**
- Create: `.github/workflows/go-release.yml`

- [ ] **Step 1: Write workflow**

```yaml
name: Go Release

on:
  push:
    tags: ['v*']

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - goos: linux
            goarch: amd64
          - goos: linux
            goarch: arm64
          - goos: darwin
            goarch: amd64
          - goos: darwin
            goarch: arm64
          - goos: windows
            goarch: amd64

    steps:
      - uses: actions/checkout@v4

      - name: Set up Go
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'

      - name: Build
        working-directory: archie-tui
        env:
          GOOS: ${{ matrix.goos }}
          GOARCH: ${{ matrix.goarch }}
        run: |
          EXT=""
          if [ "$GOOS" = "windows" ]; then EXT=".exe"; fi
          go build -ldflags "-s -w -X main.version=${GITHUB_REF_NAME#v}" \
            -o ../archie-code-${{ matrix.goos }}-${{ matrix.goarch }}${EXT} .

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: archie-code-${{ matrix.goos }}-${{ matrix.goarch }}
          path: archie-code-*

  release:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Download all artifacts
        uses: actions/download-artifact@v4
        with:
          merge-multiple: true

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          files: archie-code-*
          generate_release_notes: true
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain && git add .github/workflows/go-release.yml && git commit -m "ci: Go cross-compile + GitHub release on tag push"
```

---

### Task 7.6: Push and close out

- [ ] **Step 1: Push**
- [ ] **Step 2: Log decision + update project understanding to 90%**
