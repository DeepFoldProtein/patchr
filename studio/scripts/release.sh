#!/usr/bin/env bash
set -euo pipefail

#
# release.sh — Build Patchr Studio for mac/win/linux, create a GitHub release, and upload artifacts.
#
# Usage:
#   ./scripts/release.sh                  # build all platforms (mac on macOS, linux/win cross-compile)
#   ./scripts/release.sh --mac            # macOS only
#   ./scripts/release.sh --win            # Windows only
#   ./scripts/release.sh --linux          # Linux only
#   ./scripts/release.sh --mac --linux    # multiple platforms
#   ./scripts/release.sh --version 1.2.0  # set version (updates package.json)
#   ./scripts/release.sh --draft          # create as draft release
#   ./scripts/release.sh --no-upload      # build only, skip GitHub release
#
# macOS code-signing & notarization env vars (from .env):
#   APPLE_SIGNING_IDENTITY   — "Developer ID Application: ..."
#   APPLE_TEAM_ID            — 10-char team ID
#   APPLE_ID                 — Apple ID email for notarytool
#   APPLE_PASSWORD           — App-specific password
#   APPLE_CERTIFICATE        — Base64-encoded .p12 certificate (CI)
#   APPLE_CERTIFICATE_PASSWORD — Password for the .p12 (CI)
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ── Parse args ────────────────────────────────────────────────────────────────
BUILD_MAC=false
BUILD_WIN=false
BUILD_LINUX=false
DRAFT=false
NO_UPLOAD=false
EXPLICIT_PLATFORM=false
CUSTOM_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mac)    BUILD_MAC=true;   EXPLICIT_PLATFORM=true ;;
    --win)    BUILD_WIN=true;   EXPLICIT_PLATFORM=true ;;
    --linux)  BUILD_LINUX=true; EXPLICIT_PLATFORM=true ;;
    --draft)  DRAFT=true ;;
    --no-upload) NO_UPLOAD=true ;;
    --version)
      shift
      CUSTOM_VERSION="$1"
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

# Default: build all platforms
if [ "$EXPLICIT_PLATFORM" = false ]; then
  BUILD_MAC=true
  BUILD_WIN=true
  BUILD_LINUX=true
fi

# ── Load .env if present ─────────────────────────────────────────────────────
if [ -f "$PROJECT_DIR/.env" ]; then
  echo "📄 Loading .env"
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

# ── Version ──────────────────────────────────────────────────────────────────
if [ -n "$CUSTOM_VERSION" ]; then
  # Update package.json version (no git tag from npm)
  npm version "$CUSTOM_VERSION" --no-git-tag-version
  echo "📝 Updated package.json version to $CUSTOM_VERSION"
fi
VERSION=$(node -p "require('./package.json').version")
TAG="v${VERSION}"
echo "🏷  Version: $VERSION  Tag: $TAG"

# ── Preflight checks ─────────────────────────────────────────────────────────
if [ "$NO_UPLOAD" = false ]; then
  if ! command -v gh &>/dev/null; then
    echo "❌ GitHub CLI (gh) is required. Install: https://cli.github.com"
    exit 1
  fi
  if ! gh auth status &>/dev/null; then
    echo "❌ Not authenticated with gh. Run: gh auth login"
    exit 1
  fi
fi

# ── Install dependencies ─────────────────────────────────────────────────────
echo "📦 Installing dependencies..."
npm ci

# ── Build renderer + main ────────────────────────────────────────────────────
echo "🔨 Building app..."
npx electron-vite build

# ── macOS: Setup signing & notarization ──────────────────────────────────────
BUILD_KEYCHAIN=""

cleanup_keychain() {
  if [ -n "$BUILD_KEYCHAIN" ] && [ -f "$BUILD_KEYCHAIN" ]; then
    echo "🧹 Cleaning up build keychain..."
    security delete-keychain "$BUILD_KEYCHAIN" 2>/dev/null || true
  fi
  rm -f /tmp/build_certificate.p12 /tmp/DeveloperIDG2CA.cer
}

setup_mac_signing() {
  if [ -z "${APPLE_CERTIFICATE:-}" ]; then
    if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
      export CSC_NAME="$APPLE_SIGNING_IDENTITY"
      echo "✅ Code signing identity: $CSC_NAME (from local keychain)"
    else
      echo "⏭  No signing certificate — build will be unsigned"
    fi
  else
    echo "🔐 Setting up code signing from APPLE_CERTIFICATE..."

    # 1. Decode p12
    printf '%s' "$APPLE_CERTIFICATE" | base64 --decode > /tmp/build_certificate.p12

    # 2. Download Apple Developer ID intermediate CA (G2)
    echo "📥 Downloading Apple Developer ID G2 intermediate certificate..."
    curl -sL https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer -o /tmp/DeveloperIDG2CA.cer

    # 3. Create temporary keychain
    BUILD_KEYCHAIN="/tmp/build_signing.keychain-db"
    KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
    security delete-keychain "$BUILD_KEYCHAIN" 2>/dev/null || true
    security create-keychain -p "$KEYCHAIN_PASSWORD" "$BUILD_KEYCHAIN"
    security set-keychain-settings -lut 21600 "$BUILD_KEYCHAIN"
    security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$BUILD_KEYCHAIN"

    # 4. Import intermediate CA first (builds the trust chain)
    security import /tmp/DeveloperIDG2CA.cer -k "$BUILD_KEYCHAIN" \
      -T /usr/bin/codesign -T /usr/bin/productbuild

    # 5. Import developer p12 (cert + private key)
    security import /tmp/build_certificate.p12 -k "$BUILD_KEYCHAIN" \
      -P "${APPLE_CERTIFICATE_PASSWORD:-}" \
      -T /usr/bin/codesign -T /usr/bin/productbuild

    # 6. Allow codesign access without GUI prompt
    security set-key-partition-list -S apple-tool:,apple:,codesign: \
      -s -k "$KEYCHAIN_PASSWORD" "$BUILD_KEYCHAIN"

    # 7. Add build keychain to search list (prepend so it's found first)
    security list-keychains -d user -s "$BUILD_KEYCHAIN" $(security list-keychains -d user | tr -d '"')

    # 8. Verify
    echo "🔍 Verifying code signing identity..."
    IDENTITY_COUNT=$(security find-identity -v -p codesigning "$BUILD_KEYCHAIN" | grep -c "valid identities found" || true)
    security find-identity -v -p codesigning "$BUILD_KEYCHAIN"

    if security find-identity -v -p codesigning "$BUILD_KEYCHAIN" | grep -q '"Developer ID'; then
      echo "✅ Developer ID certificate ready"
    else
      echo "❌ Developer ID certificate not found in keychain"
      exit 1
    fi

    # Tell electron-builder to use our keychain (skip its own keychain logic)
    export CSC_KEYCHAIN="$BUILD_KEYCHAIN"
    export CSC_LINK="/tmp/build_certificate.p12"
    export CSC_KEY_PASSWORD="${APPLE_CERTIFICATE_PASSWORD:-}"

    # Cleanup on exit
    trap cleanup_keychain EXIT
  fi

  if [ -n "${APPLE_TEAM_ID:-}" ]; then
    export APPLE_TEAM_ID
  fi

  # Configure notarization
  if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    export APPLE_NOTARIZE=true
    echo "✅ Notarization enabled for $APPLE_ID"
  else
    echo "⚠️  Notarization skipped (APPLE_ID, APPLE_PASSWORD, or APPLE_TEAM_ID not set)"
  fi
}

# ── Platform builds ──────────────────────────────────────────────────────────
ARTIFACTS=()

collect_artifacts() {
  local pattern="$1"
  while IFS= read -r -d '' file; do
    ARTIFACTS+=("$file")
  done < <(find "$PROJECT_DIR/dist" -maxdepth 1 -name "$pattern" -print0 2>/dev/null)
}

if [ "$BUILD_MAC" = true ]; then
  echo ""
  echo "🍎 Building macOS..."
  setup_mac_signing

  BUILDER_ARGS=(--mac)

  # Enable notarization via env vars (electron-builder reads these directly)
  if [ "${APPLE_NOTARIZE:-}" = true ]; then
    export APPLE_ID
    export APPLE_APP_SPECIFIC_PASSWORD="${APPLE_PASSWORD}"
    export APPLE_TEAM_ID
    # Override notarize: false in yml
    BUILDER_ARGS+=(-c.mac.notarize=true)
    echo "✅ Notarization env vars exported"
  fi

  # CSC_NAME is already exported — electron-builder reads it automatically
  npx electron-builder "${BUILDER_ARGS[@]}"
  collect_artifacts "*.dmg"
  collect_artifacts "*.zip"
  echo "✅ macOS build complete"
fi

if [ "$BUILD_WIN" = true ]; then
  echo ""
  echo "🪟 Building Windows..."
  USE_SYSTEM_WINE=true npx electron-builder --win
  collect_artifacts "*-setup.exe"
  collect_artifacts "*.msi"
  echo "✅ Windows build complete"
fi

if [ "$BUILD_LINUX" = true ]; then
  echo ""
  echo "🐧 Building Linux..."
  npx electron-builder --linux
  collect_artifacts "*.AppImage"
  collect_artifacts "*.deb"

  echo "✅ Linux build complete"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "📦 Build artifacts:"
for f in "${ARTIFACTS[@]}"; do
  echo "   $(basename "$f")  ($(du -h "$f" | cut -f1))"
done

if [ "$NO_UPLOAD" = true ]; then
  echo ""
  echo "🏁 Done (--no-upload). Artifacts in dist/"
  exit 0
fi

# ── Create GitHub release & upload ───────────────────────────────────────────
echo ""
echo "🚀 Creating GitHub release $TAG..."

GH_ARGS=(
  "$TAG"
  --title "Patchr Studio $TAG"
  --generate-notes
)

if [ "$DRAFT" = true ]; then
  GH_ARGS+=(--draft)
fi

# Clean up existing release and tag if they exist
if gh release view "$TAG" &>/dev/null; then
  echo "🗑  Deleting existing release $TAG..."
  gh release delete "$TAG" --yes
fi
if git rev-parse "$TAG" &>/dev/null; then
  echo "🗑  Deleting existing tag $TAG..."
  git tag -d "$TAG"
  git push origin ":refs/tags/$TAG" 2>/dev/null || true
fi

# Create fresh tag and release
git tag "$TAG"
git push origin "$TAG"

if [ ${#ARTIFACTS[@]} -gt 0 ]; then
  gh release create "${GH_ARGS[@]}" "${ARTIFACTS[@]}"
else
  echo "⚠️  No artifacts found to upload"
  gh release create "${GH_ARGS[@]}"
fi

echo ""
echo "✅ Release $TAG published!"
echo "   $(gh release view "$TAG" --json url -q .url)"
