import Testing
import Foundation
@testable import ReverbKit

/// ビルド出所表示（設定画面）のロジックを検証する。
/// 配布ビルドは git ハッシュ＋日時、開発実行（Info.plist 未注入）は「開発ビルド」を出す。
@Suite struct BuildInfoTests {

    @Test func packagedBuildShowsCommitAndDate() {
        let build = BuildInfo(commit: "a1b2c3d", date: "2026-06-26 12:00")
        #expect(build.isPackaged)
        #expect(build.displayText == "a1b2c3d (2026-06-26 12:00)")
    }

    @Test func devBuildShowsPlaceholder() {
        let build = BuildInfo(commit: "dev", date: "—")
        #expect(!build.isPackaged)
        #expect(build.displayText == "開発ビルド")
    }

    @Test func currentFallsBackToDevWhenNotInjected() {
        // テスト実行バンドルには ReverbBuildCommit が無いため dev にフォールバックする。
        let build = BuildInfo.current(bundle: .main)
        #expect(!build.isPackaged)
    }
}
