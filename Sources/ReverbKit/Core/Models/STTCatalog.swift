import Foundation

/// STT（mlx-whisper）モデルの選択肢（08 §6「固定肢（large-v3 既定 / turbo）」/ 03-transcription-stt）。
///
/// 翻訳モデル・話者と異なり STT は API の動的一覧を持たない **仕様上の固定肢**。
/// 既定は品質優先で large-v3 full（ルール7）。turbo は速度が要るときの明示切替肢で、
/// 既定を勝手に turbo 化しない。
/// 導入時に mlx-whisper の最新タグを確認すること（ルール6）。
public struct STTOption: Sendable, Equatable, Identifiable {
    /// API（`settings.stt.model`）へ渡すモデル名。
    public let model: String
    /// UI 表示名。
    public let displayName: String
    /// 補足説明（品質/速度のトレードオフ）。
    public let detail: String

    public var id: String { model }

    public init(model: String, displayName: String, detail: String) {
        self.model = model
        self.displayName = displayName
        self.detail = detail
    }
}

/// STT 固定肢のカタログ。モデル名は仕様で確定した既定値であり、翻訳モデルのような
/// API 動的一覧の対象ではない（コメントで根拠を残す・ルール6）。
public enum STTCatalog {
    public static let largeV3 = STTOption(
        model: "large-v3",
        displayName: "large-v3（高品質・既定）",
        detail: "品質優先の既定。処理はやや遅い。"
    )
    public static let turbo = STTOption(
        model: "turbo",
        displayName: "turbo（高速）",
        detail: "速度優先。品質は large-v3 に劣る。"
    )

    /// 固定肢（既定を先頭に置く）。
    public static let options: [STTOption] = [largeV3, turbo]

    /// 既定モデル（品質優先・large-v3 full / ルール7）。
    public static let defaultModel = largeV3.model

    /// モデル名が固定肢に含まれるか（保存値の検証用）。
    public static func contains(_ model: String) -> Bool {
        options.contains { $0.model == model }
    }
}
