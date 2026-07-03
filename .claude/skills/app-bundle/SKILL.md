---
name: app-bundle
description: Reverb を「アイコン1つで起動する配布可能な自己完結 .app」にバンドルするワークフロー。Swift本体＋再配置可能Python＋バックエンド＋静的ffmpeg＋暫定アイコンを dist/Reverb.app に同梱し、起動・サイドカー自動起動・/health まで実機検証し、最後に /Applications へ設置（旧版を置換）して通常の起動経路に反映する。中核は scripts/build_app.sh（make app）。「アプリをバンドルして」「.app作って」「配布用ビルド」「アプリケーションバンドル」「make appして」「アイコン1つで起動できるようにして」「/Applicationsに入れて」等でトリガー。
---

# アプリケーションバンドル（配布可能な自己完結 .app）ワークフロー

Reverb を **Finder からアイコン1つ（ダブルクリック）で UI が起動し、同梱した Python バックエンドを自動でサイドカー起動する** `dist/Reverb.app` に固める。中核は `scripts/build_app.sh`（= `make app`）。このスキルはその実行・前提確認・実機検証・落とし穴回避を一気通貫で行う。

前提・規約は `AGENTS.md` を一次情報源とする（macOS/Apple Silicon 固定・ローカル完結・依存を勝手に増やさない）。

## 全体像（同梱するもの / しないもの）

| 同梱する | 内容 |
|---|---|
| `MacOS/Reverb` | Swift release バイナリ（`swift build -c release`） |
| `Resources/python-runtime` | 再配置可能 Python（python-build-standalone, astral-sh）＋バックエンド依存 |
| `Resources/backend` | バックエンド一式（`.venv`/tests/キャッシュ除外） |
| `Resources/bin/{ffmpeg,ffprobe}` | 静的ビルド |
| `Resources/AppIcon.icns` | 暫定アイコン（フォント非依存・waveform 風） |

**同梱しない（設計上の外部依存・ルール1）**: Ollama / VOICEVOX(AivisSpeech)。別サーバーアプリとして利用者環境に常駐し、アプリは localhost 接続する。バンドルに含めようとしない。

## 手順

### 1. 前提：Swift 側のバンドル相対サイドカー解決があること

Finder 起動はシェルの環境変数を継承しないため、env 解決だけだと配布 .app で `notConfigured` になる。**`SidecarConfiguration.fromBundle()`（`Sources/ReverbKit/Core/API/SidecarLauncher.swift`）と、`ReverbApp.makeDefault()` の `fromEnvironment() ?? fromBundle()` フォールバック（`Sources/Reverb/ReverbApp.swift`）が入っていること**を確認する。無ければ追加する（env 上書きを優先し、無ければ `Contents/Resources/python-runtime/bin/python3` が `backend/main.py` を起動。同梱 ffmpeg/ffprobe は `REVERB_FFMPEG_BIN`/`REVERB_FFPROBE_BIN`、import 起点は `PYTHONPATH` で渡す。絶対パスはコードに固定しない＝ルール6）。

このフォールバックには `Tests/ReverbKitTests/SidecarConfigurationTests.swift` がある。変更したら `make test` を通す。

### 2. ffmpeg の入手方針をユーザに確認

`scripts/build_app.sh` は既定で **第三者サイトから静的 ffmpeg/ffprobe をDLして同梱**する。これは「ユーザが指定していないソースからのコード取得」に当たり、自動許可でブロックされ得る。実行前に方針を確認する：

- **静的ビルドをDL**（既定・他Macでも動く完全自己完結に近い）→ 第三者バイナリDLの承認が要る。
- **システムの Homebrew 版を複製**（追加DLなし・動的リンクで移植性は限定的）。
- **同梱しない**（利用者の PATH 上 ffmpeg を使う）。

> 安全策として、**DLしたバイナリはビルド中に実行しない**（バンドルへ入れるだけ）。アイコン生成は既にインストール済みのシステム ffmpeg を使う。

### 3. ビルド実行

```sh
make app          # = ./scripts/build_app.sh
```

外部取得が走る（**事前にユーザへ周知**）：python-build-standalone（astral-sh）／PyPI（fastapi等＋mlx-whisper）／静的ffmpeg。数分かかるためバックグラウンド実行が無難。**`| tee ...; echo $?` でラップしない**（パイプが set -e の失敗を握り潰す）。`> log 2>&1; echo "RC=$?"` で終了コードを確実に拾う。

### 4. 実機検証（推測で「できた」と言わない）

成果物そのものを叩いて確かめる。

```sh
# (a) 構造・サイズ・torch除外
du -sh dist/Reverb.app
ls dist/Reverb.app/Contents/Resources/python-runtime/lib/python3.*/site-packages/ | grep -i torch || echo "torch なし(意図通り)"

# (b) 同梱Pythonでバックエンドが起動しハンドシェイク＋/health を返すか
APP="$PWD/dist/Reverb.app/Contents/Resources"
PYTHONPATH="$APP/backend" REVERB_FFMPEG_BIN="$APP/bin/ffmpeg" REVERB_FFPROBE_BIN="$APP/bin/ffprobe" \
  "$APP/python-runtime/bin/python3" "$APP/backend/main.py" > /tmp/reverb_boot.log 2>&1 &
# {"event":"ready","baseURL":...} を待ち、その baseURL に curl /health（status:ok 期待）→ kill

# (c) GUI を実起動し、子サイドカーが自動 spawn されるか
open dist/Reverb.app; sleep 6
pgrep -fl "dist/Reverb.app/Contents/MacOS/Reverb"
pgrep -fl "python-runtime/bin/python3"        # ← 子が居れば fromBundle 解決OK
osascript -e 'tell application "Reverb" to quit'   # 終了でサイドカーも親追従終了
```

`make test`（Swift 116件＋）も通す。

### 5. /Applications へ設置（最新版を通常の起動経路に反映）

`dist/Reverb.app` のままだと、利用者が普段ダブルクリック/Spotlight で開く `/Applications/Reverb.app`（過去の古いコピー）は更新されない。**同一バンドルID（`jp.acroconnect.reverb`）の旧コピーが /Applications にあると、ダブルクリック/Spotlight は /Applications の旧版を開く**ため、「更新されていない」と誤認する。最新を通常経路に反映するには /Applications へ設置する。

> `/Applications/Reverb.app` は**自分が作っていない既存アプリ**になり得る。上書き＝破壊的操作なので、設置前に対象を確認（ビルド時刻・`ReverbBuildCommit` 有無）し、ユーザ承認を取る。

```sh
osascript -e 'tell application "Reverb" to quit' 2>/dev/null; sleep 1   # 起動中なら終了
rm -rf /Applications/Reverb.app
ditto dist/Reverb.app /Applications/Reverb.app                          # 署名・属性保持
# 同一IDの旧参照を更新（ダブルクリックで新版が開くように）
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/Reverb.app
# 設置確認: ビルド時刻＋ビルドスタンプが新しいこと
/usr/libexec/PlistBuddy -c "Print :ReverbBuildCommit" -c "Print :ReverbBuildDate" /Applications/Reverb.app/Contents/Info.plist
open -b jp.acroconnect.reverb   # = ダブルクリック相当。/Applications 版が起動するか確認
```

設置後、利用者は **設定画面の「バージョン」セクション**で `ReverbBuildCommit (日時)` を見て最新かを確認できる（`make app` が Info.plist に焼き込み、`BuildInfo`／SettingsView が表示）。`-dirty` は未コミット変更込みの印。

## 落とし穴（このスキルで踏んだもの）

0. **`/Applications` に同一IDの旧コピーが残ると旧版が開く**（手順5）。「version が出ない/更新されない」の最頻原因。`mdfind -name Reverb.app` で重複を確認し、設置で解消する。日本語文字列の有無は `strings`（ASCIIのみ）でなく `grep -a` で確認する。

1. **python-build-standalone のアセットURLは `+` が `%2B`**（URLエンコード）。grep は `(%2B|\+)` で拾う。`install_only.tar.gz` を選ぶ（`install_only_stripped` ではない）。
2. **torch（約2GB）は不要**。mlx-whisper が依存宣言するが torch は `torch_whisper.py` の変換専用で、推論経路（transcribe/decoding/audio）では未使用（`import mlx_whisper` は torch 未ロードで成功）。`pip install --no-deps mlx-whisper` ＋ 必要依存（mlx numba numpy scipy tiktoken huggingface_hub tqdm more-itertools）を明示インストールして torch のDL自体を回避する。
3. **DLしたバイナリをビルド中に実行しない**（自動許可ブロックの主因）。アイコン生成はシステム ffmpeg で。
4. **パイプで終了コードを握り潰さない**（`| tee` 禁止 / `> log 2>&1; echo RC=$?`）。
5. **`dist/` は gitignore**。バンドル本体はコミットしない（生成物）。コミット対象は `scripts/build_app.sh`・Makefile の `app`・Swift の `fromBundle`・テスト・`.gitignore`。

## 制約・限界（正直に伝える）

- **未署名（ad-hoc 署名）**。他Mac配布は初回 右クリック→開く が必要。真の配布には Apple Developer 署名＋notarization が別途必要（このスキルの範囲外）。
- **Ollama / VOICEVOX は利用者環境で別途起動が必要**（同梱外・localhost 接続）。
- サイズは概ね 600MB 前後（mlx 同梱のため）。

## 完了時

`dist/Reverb.app` のパス・サイズ・検証結果（ハンドシェイク/health/子プロセス）・**設置先（/Applications）とビルドスタンプ**を日本語で簡潔に報告する。UI 目視キャプチャが取れない場合（screencapture が黒＝画面収録権限/ディスプレイ要因）はその旨を明示し、起動・接続はプロセス/HTTP で確認した事実を述べる。再ビルド＋設置は `make app` → 手順5 で再現可能。
