import Testing
import Foundation
@testable import ReverbKit

/// 仕様（01-architecture §4）の JSON サンプルがそのままデコードできることを検証する。
/// API 契約と DTO のズレを早期に検出するためのゴールデンテスト。
@Suite struct DTODecodingTests {
    private let decoder = JSONDecoder()

    @Test func decodeHealth() throws {
        let json = """
        {"status":"ok","version":"0.6.0",
         "dependencies":{"ffmpeg":true,"mlx_whisper":true,"ollama":true,"voicevox":true}}
        """
        let health = try decoder.decode(HealthResponse.self, from: Data(json.utf8))
        #expect(health.version == "0.6.0")
        #expect(health.dependencies.mlxWhisper) // snake_case マッピング確認
        #expect(health.dependencies.allAvailable)
    }

    @Test func decodeModels() throws {
        let json = #"{"default":"qwen3:30b","models":["qwen3:30b","gemma3:27b","elyza:jp8b"]}"#
        let models = try decoder.decode(ModelsResponse.self, from: Data(json.utf8))
        #expect(models.defaultModel == "qwen3:30b") // 予約語 default のマッピング確認
        #expect(models.models.count == 3)
    }

    @Test func decodeSpeakers() throws {
        let json = """
        {"default":{"speakerId":13,"name":"青山龍星","styleId":0},
         "speakers":[{"speakerId":13,"name":"青山龍星","styleId":0}]}
        """
        let speakers = try decoder.decode(SpeakersResponse.self, from: Data(json.utf8))
        #expect(speakers.defaultSpeaker.speakerId == 13)
        #expect(speakers.defaultSpeaker.name == "青山龍星")
    }

    @Test func decodeJobStatus() throws {
        let json = """
        {"jobId":"j_1","projectId":"p_1","status":"running","currentStage":"translate",
         "progress":0.42,
         "stages":[
           {"name":"extract","status":"done","progress":1.0},
           {"name":"translate","status":"running","progress":0.30},
           {"name":"mix","status":"pending","progress":0.0}],
         "error":null}
        """
        let status = try decoder.decode(JobStatus.self, from: Data(json.utf8))
        #expect(status.status == .running)
        #expect(status.currentStage == .translate)
        #expect(status.stages.first?.name == .extract)
        #expect(status.error == nil)
    }

    @Test func decodeJobResult() throws {
        let json = """
        {"projectId":"p_1","videoPath":"/m/lecture.mp4","voiceoverPath":"/p/voiceover.wav",
         "subtitlesPath":"/p/subtitles.json","duration":3600.0}
        """
        let result = try decoder.decode(JobResult.self, from: Data(json.utf8))
        #expect(result.duration == 3600.0)
        #expect(result.voiceoverPath == "/p/voiceover.wav")
    }

    @Test func decodeErrorEnvelope() throws {
        let json = """
        {"error":{"code":"OLLAMA_UNAVAILABLE","stage":"translate",
         "message":"Ollama に接続できません","retryable":true}}
        """
        let envelope = try decoder.decode(BackendErrorResponse.self, from: Data(json.utf8))
        #expect(envelope.error.code == "OLLAMA_UNAVAILABLE")
        #expect(envelope.error.retryable == true)
    }

    @Test func decodeHandshake() throws {
        let json = #"{"event":"ready","baseURL":"http://127.0.0.1:53412","pid":12345,"version":"0.6.0"}"#
        let handshake = try decoder.decode(ReadyHandshake.self, from: Data(json.utf8))
        #expect(handshake.event == "ready")
        #expect(handshake.baseURL == URL(string: "http://127.0.0.1:53412"))
        #expect(handshake.pid == 12345)
    }

    @Test func encodeCreateJobRequestRoundTrip() throws {
        let request = CreateJobRequest(
            videoPath: "/m/lecture.mp4",
            settings: JobSettings(
                stt: .init(model: "large-v3", language: nil),
                translate: .init(model: "qwen3:30b"),
                tts: .init(speakerId: 13, styleId: 0),
                mix: .confirmedInitial
            )
        )
        let data = try JSONEncoder().encode(request)
        let decoded = try decoder.decode(CreateJobRequest.self, from: data)
        #expect(decoded == request)
        #expect(decoded.settings?.mix.jaVolume == 1.0)
        #expect(decoded.settings?.mix.originalVolume == 0.08)
    }

    @Test func stageNameOrderAndDisplay() {
        #expect(StageName.allCases == [.extract, .transcribe, .translate, .subtitle, .tts, .mix])
        #expect(StageName.translate.displayName == "翻訳")
    }

    @Test func confirmedInitialVolumes() {
        // 確定初期値（ルール4・変更禁止）。
        #expect(MixSettings.confirmedInitial.jaVolume == 1.0)
        #expect(MixSettings.confirmedInitial.originalVolume == 0.08)
    }
}
