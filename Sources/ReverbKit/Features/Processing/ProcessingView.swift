import SwiftUI

/// 処理中画面（screens.md §2）。
/// 本 issue（USL-75）では土台のみ。進捗・工程別状態・キャンセルの本実装は USL-78。
public struct ProcessingView: View {
    private let jobRepository: (any JobRepository)?

    public init(jobRepository: (any JobRepository)?) {
        self.jobRepository = jobRepository
    }

    public var body: some View {
        ScreenScaffold(title: "処理中") {
            PlaceholderNote(issue: "USL-78", detail: "全体進捗・6工程の状態一覧・キャンセル")
        }
    }
}
