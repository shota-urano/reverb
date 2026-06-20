# Reverb

外国語の動画を **ローカル環境だけ** で「日本語吹き替え音声（ボイスオーバー）＋日本語字幕」付きで視聴できる Mac アプリ。

詳細は [`AGENTS.md`](./AGENTS.md) と [`docs/`](./docs) を参照。

## フロントエンド（SwiftUI / macOS）

2層サイドカー構成の UI 層。Python バックエンド（サイドカー）をローカル HTTP で連携する。

### 構成

```text
Sources/
├── Reverb/        @main アプリエントリ（実行ターゲット）
└── ReverbKit/     ロジック層（テスト可能なライブラリ）
    ├── App/         AppShell / AppSidebar / AppModel / ナビゲーション
    ├── Features/    Library / Processing / Player / Settings（画面）
    ├── Core/
    │   ├── API/       BackendClient（HTTP/SSE）, SidecarLauncher
    │   ├── Repository/ JobRepository, ModelRepository（protocol＋impl）
    │   └── Models/    API 契約と 1:1 の DTO（Codable）
    └── Components/   共通部品（LocalOnlyStatus 等）
Tests/ReverbKitTests/  DTO デコード・接続ライフサイクル
```

### ビルド / テスト

```sh
make build   # swift build
make test    # swift test（Command Line Tools 環境では Testing の探索パスを自動付与）
make run     # アプリ起動
```

> full Xcode 環境では `swift test` を直接実行できる。Command Line Tools のみの環境向けに
> `make test` が Swift Testing の framework パスを補う。

### サイドカー起動コマンド

baseURL・ポートはハンドシェイクで受領するためハードコードしない（01-architecture §3.1）。
バックエンドの起動コマンドは環境変数で渡す。

```sh
export REVERB_BACKEND_EXECUTABLE=/path/to/python
export REVERB_BACKEND_ARGS="-m backend.main"
```

未設定時は接続画面で「起動コマンド未設定」を表示する（黙って成功しない）。
