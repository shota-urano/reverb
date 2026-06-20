import Foundation

/// 表示用の純粋な整形ヘルパー（UI 非依存・テスト対象）。
///
/// 進捗の重みや字幕の再分割など、**UI 側でロジックを足さない**方針なので、
/// ここに置くのは見せ方だけの変換に限る。
public enum ReverbFormat {

    /// 秒をタイムコードに整形する。1 時間以上は `h:mm:ss`、未満は `m:ss`。
    public static func timecode(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds > 0 else { return "0:00" }
        let total = Int(seconds.rounded())
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let secs = total % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, secs)
        }
        return String(format: "%d:%02d", minutes, secs)
    }

    /// 0.0〜1.0 の比率を百分率の整数文字列にする（"100%"）。範囲外はクランプ。
    public static func percent(_ ratio: Double) -> String {
        let clamped = min(max(ratio, 0), 1)
        return "\(Int((clamped * 100).rounded()))%"
    }

    /// 言語ペア表示（"英語 → 日本語"）。元言語が未判定（nil）なら "自動判定 → 日本語"。
    /// 言語の表示名は API 由来の値を渡す（UI でコード→名称の対応表を持たない）。
    public static func languagePair(source: String?, target: String = "日本語") -> String {
        let from = (source?.isEmpty == false) ? source! : "自動判定"
        return "\(from) → \(target)"
    }
}
