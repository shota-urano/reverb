import Foundation
import AVFoundation

/// 同期再生の配線（07 §4.1 方式A・2系統再生）。
///
/// - **映像＋元音声**: `videoPlayer`（元動画）。`volume` を元音声ゲインに割り当てる。
/// - **日本語吹き替え**: `voiceoverPlayer`（`voiceover.wav`）。`volume` を日本語ゲインに割り当てる。
///
/// 映像プレーヤーをマスタークロックとし、周期オブザーバで現在時刻を `PlayerViewModel` に報告、
/// 吹き替えプレーヤーをその時刻へ追従させる（ドリフトは閾値超過時に再シークで吸収）。
/// AVFoundation はこのクラスに閉じ込め、状態遷移・字幕選択は VM 側でテストする（ルール3）。
///
/// > 注: 現状バックエンド（USL-74 mix）は `voiceover.wav` に元音声を 8% で焼き込む方式B。
/// > 方式A（日本語のみトラック）へ移行するまで、元音声ゲインには焼き込み分の残差が残る（PR で連携）。
@MainActor
final class PlaybackCoordinator {
    let videoPlayer = AVPlayer()
    private let voiceoverPlayer = AVPlayer()

    /// マスター時刻の報告（秒）。
    var onTime: ((Double) -> Void)?
    /// 尺が判明したときの報告（秒）。
    var onDuration: ((Double) -> Void)?
    /// 終端到達の通知。
    var onReachEnd: (() -> Void)?

    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?

    /// 吹き替えと映像のズレがこの秒数を超えたら再シークで揃える。
    private let driftTolerance = 0.25

    deinit {
        // deinit は nonisolated。AVPlayer の解放は安全だが、メインアクター隔離のプロパティ除去は
        // teardown() の明示呼び出しに委ねる（View の onDisappear から呼ぶ）。
    }

    /// 成果物パスを割り当てて再生準備する。
    /// 別ジョブへ切替える際の再構成に備え、毎回 `teardown()` で既存の観測を外してから張り直す
    /// （View は再マウントされず @State が残るため、ここで明示的に作り直す必要がある）。
    func configure(videoPath: String, voiceoverPath: String) {
        teardown()

        let videoItem = AVPlayerItem(url: URL(fileURLWithPath: videoPath))
        let voiceoverItem = AVPlayerItem(url: URL(fileURLWithPath: voiceoverPath))
        videoPlayer.replaceCurrentItem(with: videoItem)
        voiceoverPlayer.replaceCurrentItem(with: voiceoverItem)
        videoPlayer.actionAtItemEnd = .pause
        voiceoverPlayer.actionAtItemEnd = .pause

        timeObserver = videoPlayer.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.2, preferredTimescale: 600),
            queue: .main
        ) { [weak self] time in
            MainActor.assumeIsolated {
                self?.handleTick(time)
            }
        }

        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: videoItem,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.onReachEnd?()
            }
        }
    }

    func setPlaying(_ playing: Bool) {
        if playing {
            videoPlayer.play()
            voiceoverPlayer.play()
        } else {
            videoPlayer.pause()
            voiceoverPlayer.pause()
        }
    }

    /// 両プレーヤーを同時刻へシークする（字幕・元音声・吹き替えを揃える / 08 §5.3）。
    func seek(toSeconds seconds: Double) {
        let time = CMTime(seconds: max(seconds, 0), preferredTimescale: 600)
        videoPlayer.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
        voiceoverPlayer.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    /// 日本語（主）ゲイン。
    func setJapaneseVolume(_ value: Float) {
        voiceoverPlayer.volume = value
    }

    /// 元音声ゲイン。
    func setOriginalVolume(_ value: Float) {
        videoPlayer.volume = value
    }

    /// オブザーバを外して再生を止める（View の onDisappear から呼ぶ）。
    func teardown() {
        if let timeObserver {
            videoPlayer.removeTimeObserver(timeObserver)
            self.timeObserver = nil
        }
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
            self.endObserver = nil
        }
        videoPlayer.pause()
        voiceoverPlayer.pause()
    }

    private func handleTick(_ time: CMTime) {
        let seconds = time.seconds
        guard seconds.isFinite else { return }
        onTime?(seconds)

        if let duration = videoPlayer.currentItem?.duration.seconds, duration.isFinite, duration > 0 {
            onDuration?(duration)
        }

        // 吹き替えをマスター（映像）へ追従させる。ドリフトが小さいうちは触らない。
        let voiceoverSeconds = voiceoverPlayer.currentTime().seconds
        if voiceoverSeconds.isFinite, abs(voiceoverSeconds - seconds) > driftTolerance {
            voiceoverPlayer.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
        }
    }
}
