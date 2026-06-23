import Testing
import Foundation
@testable import ReverbKit

/// 共通コンポーネントの純粋ロジック（整形・状態表示・正規化・トークン）を検証する（USL-76）。
/// View 本体ではなく、UI から切り出したテスト可能な部分のみを対象にする。
@Suite struct ComponentPresentationTests {

    // MARK: - ReverbFormat.timecode

    @Test func timecodeUnderOneHour() {
        #expect(ReverbFormat.timecode(0) == "0:00")
        #expect(ReverbFormat.timecode(59) == "0:59")
        #expect(ReverbFormat.timecode(60) == "1:00")
        #expect(ReverbFormat.timecode(125) == "2:05")
    }

    @Test func timecodeOverOneHour() {
        #expect(ReverbFormat.timecode(3600) == "1:00:00")
        #expect(ReverbFormat.timecode(3661) == "1:01:01")
    }

    @Test func timecodeRejectsInvalidInput() {
        #expect(ReverbFormat.timecode(-5) == "0:00")
        #expect(ReverbFormat.timecode(.nan) == "0:00")
        #expect(ReverbFormat.timecode(.infinity) == "0:00")
    }

    // MARK: - ReverbFormat.percent（確定初期値 100% / 8% を含む）

    @Test func percentFormatsRatio() {
        #expect(ReverbFormat.percent(1.0) == "100%")
        #expect(ReverbFormat.percent(0.08) == "8%") // 元音声 初期値（ルール4）
        #expect(ReverbFormat.percent(0.5) == "50%")
    }

    @Test func percentClampsOutOfRange() {
        #expect(ReverbFormat.percent(1.5) == "100%")
        #expect(ReverbFormat.percent(-0.2) == "0%")
    }

    @Test func confirmedInitialBalanceRendersAsSpec() {
        // AudioBalanceControl の初期表示が 100% / 8% であること（ルール4・変更禁止）。
        #expect(ReverbFormat.percent(MixSettings.confirmedInitial.jaVolume) == "100%")
        #expect(ReverbFormat.percent(MixSettings.confirmedInitial.originalVolume) == "8%")
    }

    // MARK: - ReverbFormat.languagePair

    @Test func languagePairWithAndWithoutSource() {
        #expect(ReverbFormat.languagePair(source: "英語") == "英語 → 日本語")
        #expect(ReverbFormat.languagePair(source: nil) == "自動判定 → 日本語")
        #expect(ReverbFormat.languagePair(source: "") == "自動判定 → 日本語")
    }

    // MARK: - StageState 表示（§5.4）

    @Test func stageStateLabels() {
        #expect(StageState.pending.statusLabel == "待機中")
        #expect(StageState.running.statusLabel == "実行中")
        #expect(StageState.done.statusLabel == "完了")
        #expect(StageState.failed.statusLabel == "失敗")
        #expect(StageState.canceled.statusLabel == "キャンセル済み")
    }

    @Test func stageStateRoles() {
        // done は青いチェック＝accent、running は accent、failed は error、その他は中立（§5.4）。
        #expect(StageState.done.role == .accent)
        #expect(StageState.running.role == .accent)
        #expect(StageState.failed.role == .error)
        #expect(StageState.pending.role == .neutral)
        #expect(StageState.canceled.role == .neutral)
    }

    // MARK: - JobState 表示

    @Test func jobStateLabels() {
        #expect(JobState.queued.statusLabel == "準備中")
        #expect(JobState.running.statusLabel == "処理中")
        #expect(JobState.done.statusLabel == "視聴できます")
        #expect(JobState.failed.statusLabel == "失敗")
        #expect(JobState.canceled.statusLabel == "キャンセル済み")
    }

    // MARK: - StageOrder.normalized（固定順・欠け補完）

    @Test func normalizedFillsAllSixInFixedOrder() {
        let partial = [
            StageProgress(name: .translate, status: .running, progress: 0.3),
            StageProgress(name: .extract, status: .done, progress: 1.0),
        ]
        let result = StageOrder.normalized(partial)
        #expect(result.map(\.name) == StageName.allCases) // extract→…→mix
        #expect(result.count == 6)
        // 提供済みの値は保持。
        #expect(result[0].status == .done)        // extract
        #expect(result[2].status == .running)     // translate
        // 未提供は pending 補完。
        #expect(result[5].name == .mix)
        #expect(result[5].status == .pending)
    }

    @Test func normalizedDeduplicatesByFirstOccurrence() {
        let dupes = [
            StageProgress(name: .mix, status: .running, progress: 0.5),
            StageProgress(name: .mix, status: .done, progress: 1.0),
        ]
        let result = StageOrder.normalized(dupes)
        #expect(result.count == 6)
        #expect(result.last?.name == .mix)
        #expect(result.last?.status == .running) // 最初の出現を採用
    }

    // MARK: - DependencyCatalog（固定順・対応エンジン）

    @Test func dependencyCatalogOrderAndMapping() {
        let status = DependencyStatus(ffmpeg: true, mlxWhisper: false, ollama: true, tts: false)
        let items = DependencyCatalog.items(from: status)
        #expect(items.map(\.name) == ["ffmpeg", "mlx-whisper", "Ollama", "TTS"])
        #expect(items.map(\.available) == [true, false, true, false])
    }

    // MARK: - デザイントークン（§4 形状 / §7 アクセシビリティの確定範囲）

    @Test func shapeTokensWithinSpecRange() {
        #expect((12.0 ... 14.0).contains(ReverbTheme.Radius.player))      // プレーヤー角丸
        #expect((8.0 ... 10.0).contains(ReverbTheme.Radius.button))       // ボタン角丸
        #expect(ReverbTheme.Radius.thumbnail == 8)                        // サムネイル角丸
        #expect((30.0 ... 34.0).contains(ReverbTheme.Metrics.formControlHeight))
    }

    @Test func hitTargetTokensMeetAccessibilityMinimum() {
        #expect(ReverbTheme.Metrics.minHitTarget >= 28)      // §7: 最低 28pt
        #expect(ReverbTheme.Metrics.primaryHitTarget >= 32)  // §7: 主要操作 32pt 以上
    }
}
