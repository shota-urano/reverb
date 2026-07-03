import SwiftUI
import AppKit
import ReverbKit

/// アプリのエントリ（@main）。実体は ReverbKit 側の AppShell / AppModel。
/// サイドカー起動コマンドは環境変数で解決（パスをコードに固定しない / §3.1・ルール6）。
@main
struct ReverbApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
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

/// 起動時にアプリを通常アプリ化する（USL-90）。
/// `swift run` 直起動や活性化ポリシー次第ではアクセサリ（background-only）として起動し、
/// メニューバーやネイティブ・フルスクリーン（NSWindow.toggleFullScreen）が無効化される。
/// `.regular` 化でこれらを有効にする。本番 `.app`（LSUIElement 無し）とも整合する。
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

extension AppModel {
    /// 本番構成の AppModel を生成する。
    /// サイドカー起動コマンドが未設定なら、接続時に「未設定」エラーとして UI に表示する。
    @MainActor
    static func makeDefault() -> AppModel {
        // env 指定（開発時の上書き）を優先し、無ければ同梱バンドル（配布 .app）を解決する。
        let launcher: any SidecarLauncher
        if let configuration = SidecarConfiguration.fromEnvironment()
            ?? SidecarConfiguration.fromBundle() {
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
