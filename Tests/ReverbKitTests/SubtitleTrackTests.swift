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
}
