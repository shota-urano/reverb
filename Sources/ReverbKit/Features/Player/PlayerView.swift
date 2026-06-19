import SwiftUI

/// プレーヤー画面（screens.md §3）。
/// 本 issue（USL-75）では土台のみ。同期再生・字幕・音量バランスの本実装は USL-79。
public struct PlayerView: View {
    private let jobRepository: (any JobRepository)?

    public init(jobRepository: (any JobRepository)?) {
        self.jobRepository = jobRepository
    }

    public var body: some View {
        ScreenScaffold(title: "プレーヤー") {
            PlaceholderNote(issue: "USL-79", detail: "AVKit 同期再生・字幕・オーディオバランス")
        }
    }
}
