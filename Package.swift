// swift-tools-version: 6.0
import PackageDescription

// Reverb — 外国語動画をローカルだけで日本語吹き替え＋字幕視聴する Mac アプリ。
// USL-75: アプリ基盤・ナビゲーション・バックエンド連携（2層サイドカー / ローカルHTTP）。
//
// 構成:
//   ReverbKit ... テスト可能なロジック層（DTO / BackendClient / SidecarLauncher /
//                 Repository / AppModel / Views）。AGENTS.md の Reverb/ ツリー
//                 （App / Features / Core / Components）をこのターゲット配下に置く。
//   Reverb    ... @main アプリ実行ターゲット（エントリのみ）。
let package = Package(
    name: "Reverb",
    platforms: [
        // macOS / Apple Silicon 固定（ルール10）。最小サポートは .v14（@Observable 利用）。
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "Reverb",
            dependencies: ["ReverbKit"],
            path: "Sources/Reverb"
        ),
        .target(
            name: "ReverbKit",
            path: "Sources/ReverbKit"
        ),
        .testTarget(
            name: "ReverbKitTests",
            dependencies: ["ReverbKit"],
            path: "Tests/ReverbKitTests"
        ),
    ]
)
