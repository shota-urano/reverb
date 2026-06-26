import Testing
import Foundation
@testable import ReverbKit

/// `subtitles.json`（09-data-model §3.4）のデコードと cue 選択ロジックを検証する。
/// API/データ契約と DTO のズレを早期に検出するゴールデンテストを含む。
@Suite struct SubtitleTrackTests {
    private let decoder = JSONDecoder()

    /// 仕様 09 §3.4 のサンプル JSON がそのままデコードできる。
    @Test func decodesSpecSample() throws {
        let json = """
        {
          "version": 1,
          "cues": [
            { "id": 0, "start": 0.0,  "end": 4.2,  "lines": ["講義へようこそ。"], "segmentIds": [0] },
            { "id": 1, "start": 4.2,  "end": 9.8,  "lines": ["本日は字幕整形について", "解説します。"], "segmentIds": [1] }
          ]
        }
        """
        let track = try decoder.decode(SubtitleTrack.self, from: Data(json.utf8))
        #expect(track.version == 1)
        #expect(track.cues.count == 2)
        #expect(track.cues[1].lines == ["本日は字幕整形について", "解説します。"])
        #expect(track.cues[1].segmentIds == [1])
    }

    /// segmentIds が無くても寛容にデコードする（表示には不要なため）。
    @Test func decodesWithoutSegmentIds() throws {
        let json = #"{"version":1,"cues":[{"id":0,"start":0.0,"end":2.0,"lines":["あ"]}]}"#
        let track = try decoder.decode(SubtitleTrack.self, from: Data(json.utf8))
        #expect(track.cues.first?.segmentIds == nil)
        #expect(track.cues.first?.lines == ["あ"])
    }

    // MARK: - cue(at:) 半開区間 [start, end)

    private let track = SubtitleTrack(version: 1, cues: [
        SubtitleCue(id: 0, start: 0.0, end: 4.2, lines: ["一"]),
        SubtitleCue(id: 1, start: 4.2, end: 9.8, lines: ["二"]),
        SubtitleCue(id: 2, start: 12.0, end: 14.0, lines: ["三"]), // 前 cue との間に無音区間
    ])

    @Test func selectsCueContainingTime() {
        #expect(track.cue(at: 0.0)?.id == 0)   // start は含む
        #expect(track.cue(at: 3.0)?.id == 0)
        #expect(track.cue(at: 4.2)?.id == 1)   // 境界は次の cue（end は含まない）
        #expect(track.cue(at: 9.79)?.id == 1)
    }

    @Test func returnsNilOutsideAnyCue() {
        #expect(track.cue(at: 9.8) == nil)     // end ちょうどは非表示
        #expect(track.cue(at: 10.5) == nil)    // 無音区間
        #expect(track.cue(at: 100.0) == nil)   // 末尾より後
        #expect(track.cue(at: -1.0) == nil)    // 負時刻
    }

    @Test func returnsNilForNonFiniteTime() {
        #expect(track.cue(at: .nan) == nil)
        #expect(track.cue(at: .infinity) == nil)
    }

    @Test func emptyTrackHasNoCue() {
        let empty = SubtitleTrack(version: 1, cues: [])
        #expect(empty.cue(at: 0.0) == nil)
    }

    // MARK: - audioStart/audioEnd（吹き替え音声配置への同期）

    /// audioStart/audioEnd があればデコードし、無い既存 JSON は nil。
    @Test func decodesAudioPlacementFields() throws {
        let json = #"""
        {"version":1,"cues":[
          {"id":0,"start":0.0,"end":2.0,"lines":["一"],"audioStart":0.0,"audioEnd":2.5},
          {"id":1,"start":2.0,"end":4.0,"lines":["二"]}
        ]}
        """#
        let track = try decoder.decode(SubtitleTrack.self, from: Data(json.utf8))
        #expect(track.cues[0].audioStart == 0.0)
        #expect(track.cues[0].audioEnd == 2.5)
        #expect(track.cues[1].audioStart == nil)
        #expect(track.cues[1].audioEnd == nil)
    }

    /// audioStart/audioEnd がある cue は、元 start/end ではなく音声配置時刻で選択される。
    @Test func selectsByAudioWindowWhenPresent() {
        // 元字幕は 0-2 / 2-4 だが、音声は尺合わせで後ろへドリフト（0-3 / 3-6.5）。
        let drifted = SubtitleTrack(version: 1, cues: [
            SubtitleCue(id: 0, start: 0.0, end: 2.0, lines: ["一"], audioStart: 0.0, audioEnd: 3.0),
            SubtitleCue(id: 1, start: 2.0, end: 4.0, lines: ["二"], audioStart: 3.0, audioEnd: 6.5),
        ])
        // 元時刻 2.5 は元では cue1 だが、音声窓では cue0（音声がまだ鳴っている）。
        #expect(drifted.cue(at: 2.5)?.id == 0)
        #expect(drifted.cue(at: 3.0)?.id == 1)   // 音声窓の境界は次 cue
        #expect(drifted.cue(at: 6.4)?.id == 1)
        #expect(drifted.cue(at: 6.5) == nil)      // 音声終了ちょうどは非表示
    }

    /// audio フィールドが無い cue は従来どおり元 start/end で選択（後方互換）。
    @Test func fallsBackToOriginalTimingWithoutAudioFields() {
        let cue = SubtitleCue(id: 0, start: 1.0, end: 3.0, lines: ["一"])
        #expect(cue.displayStart == 1.0)
        #expect(cue.displayEnd == 3.0)
    }
}
