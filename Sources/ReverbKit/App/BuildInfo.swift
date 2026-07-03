import Foundation

/// アプリの「ビルド出所」をアプリ側で確認するための情報。
///
/// 配布 .app では `make app`（scripts/build_app.sh）が Info.plist に git コミットハッシュと
/// ビルド日時を焼き込む。これを設定画面に表示し、「いつ・どのコミットから作った .app か」を
/// 利用者が一目で確認できるようにする（中身を更新しても固定の version では判別できないため）。
/// 開発実行（`swift run`・Info.plist 未注入）では dev 値を返す。
public struct BuildInfo: Equatable, Sendable {
    public let commit: String
    public let date: String

    public init(commit: String, date: String) {
        self.commit = commit
        self.date = date
    }

    /// 配布ビルドかどうか（Info.plist にビルド情報が焼き込まれているか）。
    public var isPackaged: Bool { commit != "dev" }

    /// 表示用の1行（例: `a1b2c3d (2026-06-26 12:00)` / 開発時は `開発ビルド`）。
    public var displayText: String {
        isPackaged ? "\(commit) (\(date))" : "開発ビルド"
    }

    /// Info.plist（`ReverbBuildCommit` / `ReverbBuildDate`）から読み出す。未注入なら dev。
    public static func current(bundle: Bundle = .main) -> BuildInfo {
        let info = bundle.infoDictionary
        let commit = (info?["ReverbBuildCommit"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "dev"
        let date = (info?["ReverbBuildDate"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "—"
        return BuildInfo(commit: commit, date: date)
    }
}
