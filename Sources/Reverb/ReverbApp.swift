import SwiftUI
import ReverbKit

/// アプリのエントリ（@main）。実体は ReverbKit 側の AppShell / AppModel。
/// サイドカー起動コマンドは環境変数で解決（パスをコードに固定しない / §3.1・ルール6）。
@main
struct ReverbApp: App {
    @State private var model = AppModel.makeDefault()

    var body: some Scene {
        WindowGroup {
            AppShell(model: model)
        }
        .windowResizability(.contentMinSize)
        .commands {
            // 既定の新規ウィンドウ等は MVP では不要。
        }
    }
}

extension AppModel {
    /// 本番構成の AppModel を生成する。
    /// サイドカー起動コマンドが未設定なら、接続時に「未設定」エラーとして UI に表示する。
    @MainActor
    static func makeDefault() -> AppModel {
        let launcher: any SidecarLauncher
        if let configuration = SidecarConfiguration.fromEnvironment() {
            launcher = ProcessSidecarLauncher(configuration: configuration)
        } else {
            launcher = UnconfiguredSidecarLauncher()
        }
        return AppModel(launcher: launcher)
    }
}

/// 起動コマンド未設定時のプレースホルダ。常に notConfigured を投げる（黙って成功しない）。
private struct UnconfiguredSidecarLauncher: SidecarLauncher {
    func launch(onTerminate: @escaping @Sendable (Int32) -> Void) async throws -> ReadyHandshake {
        throw SidecarError.notConfigured
    }
    func terminate() async {}
}
