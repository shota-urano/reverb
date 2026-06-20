import Foundation

/// ジョブ作成時の設定（`POST /jobs` の `settings`）。API 契約（01-architecture §4.2）と 1:1。
///
/// モデル名・話者IDはここに固定値を持たせない（ルール5,6）。
/// 既定値はバックエンドの `/models` `/speakers` `/health` が返す値を使う。
public struct JobSettings: Codable, Sendable, Equatable {
    public var stt: STTSettings
    public var translate: TranslateSettings
    public var tts: TTSSettings
    public var mix: MixSettings

    public init(stt: STTSettings, translate: TranslateSettings, tts: TTSSettings, mix: MixSettings) {
        self.stt = stt
        self.translate = translate
        self.tts = tts
        self.mix = mix
    }
}

/// 文字起こし設定。`language == nil` は Whisper 自動判定（03-transcription-stt）。
public struct STTSettings: Codable, Sendable, Equatable {
    public var model: String
    public var language: String?

    public init(model: String, language: String?) {
        self.model = model
        self.language = language
    }
}

/// 翻訳設定。モデル名は `/models` で取得した値を設定値として渡す（ハードコード禁止・ルール5,6）。
public struct TranslateSettings: Codable, Sendable, Equatable {
    public var model: String

    public init(model: String) {
        self.model = model
    }
}

/// TTS（VOICEVOX）設定。話者IDも `/speakers` の値（ルール6）。
public struct TTSSettings: Codable, Sendable, Equatable {
    public var speakerId: Int
    public var styleId: Int

    public init(speakerId: Int, styleId: Int) {
        self.speakerId = speakerId
        self.styleId = styleId
    }
}

/// 音量バランス設定（ボイスオーバー）。
public struct MixSettings: Codable, Sendable, Equatable {
    public var jaVolume: Double
    public var originalVolume: Double

    public init(jaVolume: Double, originalVolume: Double) {
        self.jaVolume = jaVolume
        self.originalVolume = originalVolume
    }

    /// 確定初期値: 日本語100% / 元音声8%（ルール4・変更禁止）。
    /// これはモデルタグではなく仕様で確定済みの UI 初期値なので定数として保持する。
    public static let confirmedInitial = MixSettings(jaVolume: 1.0, originalVolume: 0.08)
}
