import Foundation

/// サイドバー「最近のプロジェクト」に表示する軽量モデル（design-system §5.1）。
/// サムネイル・タイトル・日時の3要素に限定する。状態に応じて遷移先が変わる。
public struct RecentProject: Identifiable, Sendable, Equatable {
    public let id: String
    public let title: String
    public let updatedAt: Date
    /// 完了ならプレーヤー、処理中なら処理画面へ（screens.md 共通ナビ）。
    public let state: JobState
    /// 処理中・参照用の jobId（あれば）。
    public let jobId: String?
    /// 16:9 サムネイル画像のローカルパス（任意）。
    public let thumbnailPath: String?

    public init(
        id: String,
        title: String,
        updatedAt: Date,
        state: JobState,
        jobId: String? = nil,
        thumbnailPath: String? = nil
    ) {
        self.id = id
        self.title = title
        self.updatedAt = updatedAt
        self.state = state
        self.jobId = jobId
        self.thumbnailPath = thumbnailPath
    }

    /// 行クリック時に開くべき画面。
    public var destination: SidebarSection {
        switch state {
        case .done:
            return .library // 完了 → プレーヤー（Library 配下のプレーヤー遷移は USL-77/79）
        case .queued, .running, .failed, .canceled:
            return .processing
        }
    }
}
