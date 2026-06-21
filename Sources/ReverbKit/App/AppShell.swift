import SwiftUI

/// アプリの最上位シェル（screens.md §5）。NavigationSplitView の2ペイン。
/// 接続状態に応じてコンテンツを切替え、サイドバー選択・最近一覧・ローカル状態は常時維持する。
public struct AppShell: View {
    @State private var model: AppModel

    public init(model: AppModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        NavigationSplitView {
            AppSidebar(model: model)
        } detail: {
            detail
                .frame(minWidth: 1100 - 230, minHeight: 760) // §1: 最小1100×760pt（コンテンツ側）
        }
        .frame(minWidth: 1100, minHeight: 760)
        .task {
            // 起動時にサイドカーを起動し、/health 確認まで行う（§3.1）。
            await model.start()
        }
    }

    @ViewBuilder
    private var detail: some View {
        switch model.connection {
        case .idle, .launching:
            ConnectingView()
        case .failed(let message):
            BackendErrorView(message: message) {
                Task { await model.retry() }
            }
        case .ready:
            content
        }
    }

    @ViewBuilder
    private var content: some View {
        // 完了プロジェクトを開いている間はプレーヤーを最前面に出す（library 配下 / screens.md §3）。
        if model.playerJobId != nil {
            PlayerView(model: model)
        } else {
            switch model.selection {
            case .library:
                LibraryView(model: model)
            case .processing:
                ProcessingView(model: model)
            case .settings:
                SettingsView(model: model)
            }
        }
    }
}

/// サイドカー起動・接続中の表示（§3.1）。
struct ConnectingView: View {
    var body: some View {
        VStack(spacing: 16) {
            ProgressView()
            Text("バックエンドに接続しています…")
                .font(.body)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// バックエンド接続失敗時の表示（§3.2・§5）。失敗は黙ってスキップせず理由を表示する。
struct BackendErrorView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.largeTitle)
                .foregroundStyle(.orange)
            Text("バックエンドに接続できません")
                .font(.title3.weight(.semibold))
            Text(message)
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Button("再試行", action: retry)
                .buttonStyle(.borderedProminent)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
