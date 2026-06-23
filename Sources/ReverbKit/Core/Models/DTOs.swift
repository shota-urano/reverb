import Foundation

// バックエンド HTTP API（01-architecture §4）の DTO。Codable で API 契約と 1:1。
// FastAPI 側 Pydantic schema が単一情報源。フィールド名は API の camelCase に揃える。

// MARK: - ヘルス / メタ

/// `GET /health` のレスポンス。
public struct HealthResponse: Codable, Sendable, Equatable {
    public let status: String
    public let version: String
    public let dependencies: DependencyStatus

    public init(status: String, version: String, dependencies: DependencyStatus) {
        self.status = status
        self.version = version
        self.dependencies = dependencies
    }
}

/// 依存エンジンの可用性（01-architecture §4.1）。JSON は `mlx_whisper` の snake_case。
public struct DependencyStatus: Codable, Sendable, Equatable {
    public let ffmpeg: Bool
    public let mlxWhisper: Bool
    public let ollama: Bool
    public let tts: Bool

    enum CodingKeys: String, CodingKey {
        case ffmpeg
        case mlxWhisper = "mlx_whisper"
        case ollama
        case tts
    }

    public init(ffmpeg: Bool, mlxWhisper: Bool, ollama: Bool, tts: Bool) {
        self.ffmpeg = ffmpeg
        self.mlxWhisper = mlxWhisper
        self.ollama = ollama
        self.tts = tts
    }

    /// 全エンジンが利用可能か。緑表示（LocalOnlyStatus）の判定に使う。
    public var allAvailable: Bool {
        ffmpeg && mlxWhisper && ollama && tts
    }
}

/// `GET /models`（翻訳モデル一覧）。`default` は Swift 予約語のため CodingKeys で対応。
public struct ModelsResponse: Codable, Sendable, Equatable {
    public let defaultModel: String
    public let models: [String]

    enum CodingKeys: String, CodingKey {
        case defaultModel = "default"
        case models
    }

    public init(defaultModel: String, models: [String]) {
        self.defaultModel = defaultModel
        self.models = models
    }
}

/// `GET /speakers`（VOICEVOX 話者一覧）。
public struct SpeakersResponse: Codable, Sendable, Equatable {
    public let defaultSpeaker: Speaker
    public let speakers: [Speaker]

    enum CodingKeys: String, CodingKey {
        case defaultSpeaker = "default"
        case speakers
    }

    public init(defaultSpeaker: Speaker, speakers: [Speaker]) {
        self.defaultSpeaker = defaultSpeaker
        self.speakers = speakers
    }
}

public struct Speaker: Codable, Sendable, Equatable, Identifiable {
    public let speakerId: Int
    public let name: String
    public let styleId: Int

    /// speakerId と styleId の組で一意。
    public var id: String { "\(speakerId)-\(styleId)" }

    public init(speakerId: Int, name: String, styleId: Int) {
        self.speakerId = speakerId
        self.name = name
        self.styleId = styleId
    }
}

// MARK: - ジョブ

/// `POST /jobs` リクエスト。`settings` 省略時はバックエンド既定（確定初期値）を使用。
public struct CreateJobRequest: Codable, Sendable, Equatable {
    public let videoPath: String
    public let settings: JobSettings?

    public init(videoPath: String, settings: JobSettings? = nil) {
        self.videoPath = videoPath
        self.settings = settings
    }
}

/// `POST /jobs` レスポンス。
public struct CreateJobResponse: Codable, Sendable, Equatable {
    public let jobId: String
    public let projectId: String
    public let status: JobState

    public init(jobId: String, projectId: String, status: JobState) {
        self.jobId = jobId
        self.projectId = projectId
        self.status = status
    }
}

/// `GET /jobs/{id}` レスポンス（進捗・ステージ状態）。
public struct JobStatus: Codable, Sendable, Equatable {
    public let jobId: String
    public let projectId: String
    public let status: JobState
    public let currentStage: StageName?
    public let progress: Double
    public let stages: [StageProgress]
    public let error: BackendErrorBody?

    public init(
        jobId: String,
        projectId: String,
        status: JobState,
        currentStage: StageName?,
        progress: Double,
        stages: [StageProgress],
        error: BackendErrorBody?
    ) {
        self.jobId = jobId
        self.projectId = projectId
        self.status = status
        self.currentStage = currentStage
        self.progress = progress
        self.stages = stages
        self.error = error
    }
}

/// 工程ごとの進捗（`JobStatus.stages` の要素）。
public struct StageProgress: Codable, Sendable, Equatable, Identifiable {
    public let name: StageName
    public let status: StageState
    public let progress: Double

    public var id: StageName { name }

    public init(name: StageName, status: StageState, progress: Double) {
        self.name = name
        self.status = status
        self.progress = progress
    }
}

/// `GET /jobs/{id}/result`（完了ジョブの成果物パス）。
public struct JobResult: Codable, Sendable, Equatable {
    public let projectId: String
    public let videoPath: String
    public let voiceoverPath: String
    public let subtitlesPath: String
    public let duration: Double

    public init(
        projectId: String,
        videoPath: String,
        voiceoverPath: String,
        subtitlesPath: String,
        duration: Double
    ) {
        self.projectId = projectId
        self.videoPath = videoPath
        self.voiceoverPath = voiceoverPath
        self.subtitlesPath = subtitlesPath
        self.duration = duration
    }
}

// MARK: - エラー

/// エラーボディ（01-architecture §5）。HTTP エラー時は `{ "error": { ... } }`、
/// `JobStatus.error` では直接この型が入る。
public struct BackendErrorBody: Codable, Sendable, Equatable, Error {
    public let code: String
    public let stage: String?
    public let message: String
    public let retryable: Bool?

    public init(code: String, stage: String?, message: String, retryable: Bool?) {
        self.code = code
        self.stage = stage
        self.message = message
        self.retryable = retryable
    }
}

/// HTTP エラーレスポンスのエンベロープ。
public struct BackendErrorResponse: Codable, Sendable, Equatable {
    public let error: BackendErrorBody

    public init(error: BackendErrorBody) {
        self.error = error
    }
}

// MARK: - SSE イベント

/// `GET /jobs/{id}/events` の `event: progress` data（部分スナップショット）。
public struct JobProgressEvent: Codable, Sendable, Equatable {
    public let currentStage: StageName?
    public let progress: Double
    public let stages: [StageProgress]

    public init(currentStage: StageName?, progress: Double, stages: [StageProgress]) {
        self.currentStage = currentStage
        self.progress = progress
        self.stages = stages
    }
}

/// `event: done` data。
public struct JobDoneEvent: Codable, Sendable, Equatable {
    public let projectId: String
    public let result: JobResult

    public init(projectId: String, result: JobResult) {
        self.projectId = projectId
        self.result = result
    }
}

/// SSE ストリームで配信されるイベント。
public enum JobEvent: Sendable, Equatable {
    case progress(JobProgressEvent)
    case done(JobDoneEvent)
}

// MARK: - サイドカー・ハンドシェイク

/// バックエンドが起動直後に標準出力へ 1 行 JSON で出すハンドシェイク（01-architecture §3.1）。
/// `{"event":"ready","baseURL":"http://127.0.0.1:53412","pid":12345,"version":"0.6.0"}`
public struct ReadyHandshake: Codable, Sendable, Equatable {
    public let event: String
    public let baseURL: URL
    public let pid: Int32
    public let version: String

    public init(event: String, baseURL: URL, pid: Int32, version: String) {
        self.event = event
        self.baseURL = baseURL
        self.pid = pid
        self.version = version
    }
}
