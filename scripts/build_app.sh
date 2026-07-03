#!/usr/bin/env bash
#
# Reverb.app バンドラ（macOS / Apple Silicon）
#
# 配布可能な自己完結 .app を生成する:
#   - Swift 本体（release ビルド）
#   - 再配置可能な Python ランタイム（python-build-standalone）＋バックエンド依存
#     （fastapi/uvicorn/pydantic/httpx/mlx-whisper。torch は不要なので除外）
#   - 静的 ffmpeg / ffprobe
#   - 暫定アイコン（AppIcon.icns）
#
# 同梱しないもの（設計上の外部依存・ルール1）: Ollama / VOICEVOX。
#   これらは別サーバーアプリとして利用者環境に常駐し、アプリは localhost 接続する。
#
# 署名は ad-hoc（ローカル実行向け）。他Mac配布には Apple 署名＋notarization が別途必要。
#
set -euo pipefail

# --- 設定 ---------------------------------------------------------------
APP_NAME="Reverb"
BUNDLE_ID="jp.acroconnect.reverb"
PY_SERIES="3.11"
ARCH="aarch64"            # Apple Silicon 固定（ルール10）
VERSION="0.6.0"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/bundle"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
CONTENTS="$APP/Contents"
RES="$CONTENTS/Resources"
MACOS="$CONTENTS/MacOS"

log() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }

# --- 1. Swift release ビルド --------------------------------------------
log "Swift release ビルド"
cd "$ROOT"
swift build -c release
BIN="$ROOT/.build/release/$APP_NAME"
[ -x "$BIN" ] || { echo "release バイナリが見つかりません: $BIN"; exit 1; }

# --- 2. クリーンな .app 骨格 --------------------------------------------
log ".app 骨格を作成"
rm -rf "$APP"
mkdir -p "$MACOS" "$RES/bin"
cp "$BIN" "$MACOS/$APP_NAME"
chmod +x "$MACOS/$APP_NAME"

# --- 3. 再配置可能 Python ランタイム ------------------------------------
mkdir -p "$BUILD"
PY_RUNTIME="$RES/python-runtime"
if [ ! -d "$BUILD/python" ]; then
  log "python-build-standalone ($PY_SERIES / $ARCH) を取得"
  PBS_JSON="$(curl -fsSL https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest)"
  # バージョン区切りは URL エンコードで %2B（= "+"）になる点に注意。
  PY_URL="$(printf '%s' "$PBS_JSON" \
    | grep -oE "https://[^\"]*cpython-${PY_SERIES}\.[0-9]+(%2B|\+)[0-9]+-${ARCH}-apple-darwin-install_only\.tar\.gz" \
    | head -1)"
  [ -n "$PY_URL" ] || { echo "python-build-standalone の URL 解決に失敗"; exit 1; }
  log "  $PY_URL"
  curl -fSL "$PY_URL" -o "$BUILD/python.tar.gz"
  tar -xzf "$BUILD/python.tar.gz" -C "$BUILD"   # -> $BUILD/python/
  rm -f "$BUILD/python.tar.gz"
fi

log "バックエンド依存を同梱 Python へインストール"
PYBIN="$BUILD/python/bin/python3"
"$PYBIN" -m pip install --upgrade pip >/dev/null
"$PYBIN" -m pip install \
  "fastapi>=0.115,<1.0" \
  "uvicorn>=0.30,<1.0" \
  "pydantic>=2.8,<3.0" \
  "httpx>=0.27,<1.0"
# mlx-whisper は torch を依存宣言するが、torch は torch_whisper.py の変換専用で
# 推論経路（transcribe/decoding/audio）では未使用。約2GB の torch DL を避けるため
# --no-deps で本体のみ入れ、推論に必要な依存だけを明示インストールする。
log "  mlx-whisper（torch 抜き）を同梱"
"$PYBIN" -m pip install --no-deps "mlx-whisper"
"$PYBIN" -m pip install \
  mlx numba numpy scipy tiktoken huggingface_hub tqdm more-itertools

log "Python ランタイムをバンドルへ複製＋スリム化"
rm -rf "$PY_RUNTIME"
cp -R "$BUILD/python" "$PY_RUNTIME"
# キャッシュ/テストを除去してサイズ削減
find "$PY_RUNTIME" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$PY_RUNTIME" -type f -name "*.pyc" -delete 2>/dev/null || true

# --- 4. バックエンド本体 ------------------------------------------------
log "バックエンドソースを同梱"
rsync -a --delete \
  --exclude '.venv' \
  --exclude 'tests' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '*.pyc' \
  "$ROOT/backend/" "$RES/backend/"

# --- 5. 静的 ffmpeg / ffprobe -------------------------------------------
log "ffmpeg / ffprobe を取得"
FF_CACHE="$BUILD/ff_cache"
mkdir -p "$FF_CACHE"
fetch_ff() {
  local name="$1" out="$RES/bin/$1" cached="$FF_CACHE/$1"
  # キャッシュ済みなら再DLしない（再ビルド時の第三者DL・再承認を避ける）。
  if [ ! -x "$cached" ]; then
    # martin-riedl の macOS arm64 静的ビルド（ffmpeg/ffprobe 個別配布）
    local url="https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/${name}.zip"
    if curl -fSL "$url" -o "$BUILD/${name}.zip" 2>/dev/null; then
      unzip -o "$BUILD/${name}.zip" -d "$BUILD/${name}_x" >/dev/null
      cp "$(find "$BUILD/${name}_x" -type f -name "$name" | head -1)" "$cached"
      chmod +x "$cached"
      rm -rf "$BUILD/${name}.zip" "$BUILD/${name}_x"
    else
      echo "  ⚠ 静的 $name の取得に失敗 → システムの $name を複製（移植性は限定的）"
      cp "$(command -v "$name")" "$cached"
      chmod +x "$cached"
    fi
  fi
  cp "$cached" "$out"
  chmod +x "$out"
}
fetch_ff ffmpeg
fetch_ff ffprobe

# --- 6. 暫定アイコン（フォント非依存・waveform 風） ----------------------
# 注意: DL したバイナリはビルド中に実行しない（バンドルへ同梱するのみ）。
# アイコン描画は既にインストール済みのシステム ffmpeg を使う。
log "暫定アイコンを生成"
ICON_FFMPEG="$(command -v ffmpeg || true)"
[ -n "$ICON_FFMPEG" ] || { echo "  ⚠ システム ffmpeg 不在 → アイコン生成をスキップ"; ICON_FFMPEG=""; }
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
SRC_PNG="$BUILD/icon_1024.png"
if [ -n "$ICON_FFMPEG" ]; then
"$ICON_FFMPEG" -y -loglevel error -f lavfi -i color=c=0x1E2030:s=1024x1024 \
  -vf "drawbox=x=300:y=430:w=60:h=164:color=0x7AA2F7:t=fill,\
drawbox=x=400:y=330:w=60:h=364:color=0x9ECEFF:t=fill,\
drawbox=x=500:y=250:w=60:h=524:color=0xBB9AF7:t=fill,\
drawbox=x=600:y=380:w=60:h=264:color=0x9ECEFF:t=fill,\
drawbox=x=700:y=460:w=60:h=104:color=0x7AA2F7:t=fill" \
  -frames:v 1 "$SRC_PNG"
  for sz in 16 32 128 256 512; do
    sips -z "$sz" "$sz" "$SRC_PNG" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
    sips -z $((sz*2)) $((sz*2)) "$SRC_PNG" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
fi

# --- 7. Info.plist / PkgInfo --------------------------------------------
# ビルド出所をアプリ側で確認できるよう、git ハッシュ＋日時を焼き込む（設定画面に表示）。
GIT_COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
  GIT_COMMIT="${GIT_COMMIT}-dirty"   # 未コミット変更込みのビルドである印
fi
BUILD_DATE="$(date '+%Y-%m-%d %H:%M')"
log "Info.plist を生成 (build ${GIT_COMMIT} / ${BUILD_DATE})"
cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>ReverbBuildCommit</key><string>$GIT_COMMIT</string>
  <key>ReverbBuildDate</key><string>$BUILD_DATE</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.video</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
printf 'APPL????' > "$CONTENTS/PkgInfo"

# --- 8. ad-hoc 署名 -----------------------------------------------------
log "ad-hoc 署名"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || \
  echo "  ⚠ codesign に失敗（未署名のまま）。初回起動は右クリック→開くで許可してください。"

SIZE="$(du -sh "$APP" | cut -f1)"
log "完成: $APP  ($SIZE)"
echo "  起動:   open \"$APP\""
echo "  注意:   Ollama / VOICEVOX は別途起動が必要（localhost 接続）。"
