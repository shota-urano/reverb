import SwiftUI

/// ライブラリ画面（screens.md §1）。
/// 本 issue（USL-75）では土台のみ。動画選択・ドロップ・一覧の本実装は USL-77。
public struct LibraryView: View {
    private let jobRepository: (any JobRepository)?
    private let modelRepository: (any ModelRepository)?

    public init(jobRepository: (any JobRepository)?, modelRepository: (any ModelRepository)?) {
        self.jobRepository = jobRepository
        self.modelRepository = modelRepository
    }

    public var body: some View {
        ScreenScaffold(title: "ライブラリ") {
            Text("外国語の動画を、日本語の吹き替えと字幕で視聴できます。")
                .font(.body)
                .foregroundStyle(.secondary)
            PlaceholderNote(issue: "USL-77", detail: "動画選択・プロジェクト一覧・ドロップ領域")
        }
    }
}
