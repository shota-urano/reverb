import Foundation

/// パイプライン工程名（固定順・全工程共通 / 01-architecture §4.2）。
/// `extract → transcribe → translate → subtitle → tts → mix`。
public enum StageName: String, Codable, Sendable, CaseIterable, Identifiable {
    case extract
    case transcribe
    case translate
    case subtitle
    case tts
    case mix

    public var id: String { rawValue }

    /// 工程の日本語表示（design-system §5.4）。UI 側で順序や重みを再計算しない。
    public var displayName: String {
        switch self {
        case .extract: return "音声抽出"
        case .transcribe: return "文字起こし"
        case .translate: return "翻訳"
        case .subtitle: return "字幕整形"
        case .tts: return "音声合成"
        case .mix: return "ミックス"
        }
    }

    /// 現在工程の短い説明（処理中画面 / screens.md §2「現在の工程名と短い説明」）。
    public var caption: String {
        switch self {
        case .extract: return "動画から音声を取り出しています"
        case .transcribe: return "音声を文字に起こしています"
        case .translate: return "日本語に翻訳しています"
        case .subtitle: return "字幕を整えています"
        case .tts: return "日本語の音声を合成しています"
        case .mix: return "吹き替えと元音声をミックスしています"
        }
    }
}

/// ジョブ全体の状態（01-architecture §4.2）。
public enum JobState: String, Codable, Sendable {
    case queued
    case running
    case done
    case failed
    case canceled
}

/// 各工程の状態（design-system §5.4）。
public enum StageState: String, Codable, Sendable {
    case pending
    case running
    case done
    case failed
    case canceled
}
