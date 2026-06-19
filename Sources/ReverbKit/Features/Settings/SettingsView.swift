import SwiftUI

/// 設定画面（screens.md §4）。
/// 本 issue（USL-75）では土台のみ。STT/翻訳/TTS/音量/依存エンジンの本実装は USL-80。
public struct SettingsView: View {
    private let modelRepository: (any ModelRepository)?

    public init(modelRepository: (any ModelRepository)?) {
        self.modelRepository = modelRepository
    }

    public var body: some View {
        ScreenScaffold(title: "設定") {
            PlaceholderNote(issue: "USL-80", detail: "STT・翻訳・TTS・初期音量・依存エンジン状態")
        }
    }
}
