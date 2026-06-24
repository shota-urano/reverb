import SwiftUI
import AVKit
import AppKit

/// プレーヤー画面（screens.md §3 / 08 §5）。
///
/// 元映像・日本語吹き替え・日本語字幕を同一時間軸で再生する。状態取得・再生制御は ViewModel
/// （Repository 経由）と PlaybackCoordinator（AVFoundation 配線）に委ね、View は描画と操作通知に
/// 徹する（ルール3）。確定初期値（日本語100%/元音声8%）を勝手に変えない（ルール4）。
public struct PlayerView: View {
    /// 遷移ハブ兼プロジェクト台帳（アクティブジョブ・概要・ナビゲーションの単一情報源）。
    private let model: AppModel
    @State private var viewModel: PlayerViewModel
    @State private var coordinator = PlaybackCoordinator()
    /// スライダー操作中の暫定割合（確定時に endScrubbing へ渡す）。
    @State private var scrubFraction: Double = 0
    /// この View をホストしている NSWindow（フルスクリーン切替の対象・USL-90）。
    @State private var hostingWindow: NSWindow?

    public init(model: AppModel) {
        self.model = model
        _viewModel = State(wrappedValue: PlayerViewModel(
            jobRepository: model.jobRepository,
            subtitleRepository: DefaultSubtitleRepository(),
            modelRepository: model.modelRepository
        ))
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: ReverbTheme.Metrics.sectionSpacing) {
            header
            // 再生レイアウトに縦スペースを譲る（末尾 Spacer に奪われないよう優先度を上げる・USL-89）。
            content
                .layoutPriority(1)
            Spacer(minLength: 0)
        }
        .padding(ReverbTheme.Metrics.contentPadding)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(WindowAccessor { hostingWindow = $0 })
        .task(id: model.playerJobId) {
            // コールバックを先に張ってから読込（最初の周期通知を取りこぼさない）。
            coordinator.onTime = { viewModel.updateObservedTime($0) }
            coordinator.onDuration = { viewModel.updateDuration($0) }
            coordinator.onReachEnd = { viewModel.playbackDidReachEnd() }
            guard let jobId = model.playerJobId else { return }
            await viewModel.load(jobId: jobId)
            syncPlaybackToCurrentJob()
        }
        .onDisappear { coordinator.teardown() }
        .onChange(of: viewModel.isPlaying) { _, playing in coordinator.setPlaying(playing) }
        .onChange(of: viewModel.seekToken) { _, _ in coordinator.seek(toSeconds: viewModel.currentTime) }
        .onChange(of: viewModel.japaneseVolume) { _, value in coordinator.setJapaneseVolume(Float(value)) }
        .onChange(of: viewModel.originalVolume) { _, value in coordinator.setOriginalVolume(Float(value)) }
    }

    /// 現在のジョブに再生層を合わせる。再生可能なら AVFoundation を（再）構成し初期音量を反映、
    /// 再生不能（成果物欠落）なら旧ジョブのメディアを止める。別ジョブへ切替えても View は再マウント
    /// されない（@State が残る）ため、ジョブ確定のたびに明示的に呼ぶ。
    private func syncPlaybackToCurrentJob() {
        guard let result = viewModel.result, viewModel.canPlay else {
            coordinator.teardown()
            return
        }
        coordinator.configure(videoPath: result.videoPath, voiceoverPath: result.voiceoverPath)
        coordinator.setJapaneseVolume(Float(viewModel.japaneseVolume))
        coordinator.setOriginalVolume(Float(viewModel.originalVolume))
    }

    // MARK: - ヘッダ

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
            Button {
                viewModel.pause()
                model.closePlayer()
            } label: {
                Label("ライブラリ", systemImage: "chevron.left")
            }
            .buttonStyle(.link)
            .accessibilityHint("プレーヤーを閉じてライブラリに戻ります")

            VStack(alignment: .leading, spacing: 8) {
                Text(model.activeProject?.title ?? "プレーヤー")
                    .font(.title.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)

                HStack(spacing: 14) {
                    metaItem(systemImage: "character.bubble", text: languagePair)
                    if let translateModel = viewModel.translateModel {
                        metaItem(systemImage: "cpu", text: translateModel)
                    }
                    LocalOnlyStatus(healthy: model.health?.dependencies.allAvailable ?? false)
                }
                .font(.callout)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }

    private var languagePair: String {
        ReverbFormat.languagePair(source: model.activeProject?.sourceLanguage)
    }

    private func metaItem(systemImage: String, text: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage)
            Text(text)
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: - 本体（フェーズ別）

    @ViewBuilder
    private var content: some View {
        switch viewModel.phase {
        case .loading:
            loadingState
        case .failed(let error):
            failureState(error)
        case .ready:
            readyContent
        }
    }

    private var loadingState: some View {
        HStack(spacing: 12) {
            ProgressView().controlSize(.small)
            Text("成果物を読み込んでいます…")
                .font(.body)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("成果物を読み込んでいます")
    }

    /// 成果物取得そのものの失敗（`GET /jobs/{id}/result`）。
    private func failureState(_ error: BackendErrorBody) -> some View {
        noticeCard(
            systemImage: "exclamationmark.triangle.fill",
            role: .error,
            title: "再生できません",
            message: error.message,
            primary: ("ライブラリへ戻る", { model.closePlayer() })
        )
    }

    @ViewBuilder
    private var readyContent: some View {
        if viewModel.videoMissing {
            // 元動画移動済み: 再選択を促す。成果物は保持される（08 §エラー）。
            noticeCard(
                systemImage: "film.stack",
                role: .warning,
                title: "元の動画が見つかりません",
                message: "元動画が移動または削除されています。ライブラリから同じ動画を選び直してください。生成済みの成果物は保持されています。",
                primary: ("ライブラリで選び直す", { model.closePlayer() })
            )
        } else if viewModel.voiceoverMissing {
            // 吹き替え音声不可: 再生開始せず再処理案内（08 §エラー）。
            noticeCard(
                systemImage: "waveform.slash",
                role: .error,
                title: "吹き替え音声を再生できません",
                message: "吹き替え音声の成果物が読み込めませんでした。ライブラリから再処理してください。",
                primary: ("ライブラリへ戻る", { model.closePlayer() })
            )
        } else {
            playbackLayout
        }
    }

    // MARK: - 再生レイアウト

    private var playbackLayout: some View {
        VStack(alignment: .leading, spacing: ReverbTheme.Metrics.sectionSpacing) {
            // 動画面に縦スペースを最優先で割り当て、コントロール・下段パネルは固有高を保つ（USL-89）。
            playerSurface
                .layoutPriority(1)
            transportControls
            if viewModel.subtitleUnavailable {
                // 字幕のみ欠落: 動画・音声は再生し、字幕エラーを明示（08 §エラー）。
                Label("字幕を読み込めませんでした。動画と音声はそのまま再生できます。", systemImage: "captions.bubble")
                    .font(.callout)
                    .foregroundStyle(StatusRole.warning.color)
                    .accessibilityElement(children: .combine)
            }
            bottomPanels
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    /// 16:9 の動画面。字幕は下部中央に重ね、再生コントロールとは別段に置く（§5.6）。
    ///
    /// 黒背景・角丸・字幕オーバーレイは **16:9 枠にフィットさせてから** 透明な伸縮フレームで
    /// 中央寄せする。背景を `.frame(maxWidth:.infinity)` の外側に塗らないことで、横長の黒帯を出さない
    /// （USL-89）。`maxHeight: .infinity` と `layoutPriority` で縦スペースを最優先に取り、動画を大きく出す。
    private var playerSurface: some View {
        VideoSurface(player: coordinator.videoPlayer)
            .aspectRatio(ReverbTheme.Player.videoAspectRatio, contentMode: .fit)
            .background(ReverbTheme.Palette.videoSurface)
            .clipShape(RoundedRectangle(cornerRadius: ReverbTheme.Radius.player))
            .overlay(alignment: .bottom) {
                SubtitleOverlay(lines: viewModel.currentLines)
                    .padding(.bottom, 24) // 再生コントロールと最低20pt離す（§5.6）
                    .padding(.horizontal, 24)
                    .allowsHitTesting(false)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("動画プレーヤー")
    }

    // MARK: - 再生コントロール（§5.3）

    private var transportControls: some View {
        VStack(spacing: 10) {
            HStack(spacing: 12) {
                Text(viewModel.currentTimecode)
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 52, alignment: .leading)

                Slider(
                    value: Binding(
                        get: { viewModel.isScrubbing ? scrubFraction : viewModel.progress },
                        set: { scrubFraction = $0; viewModel.scrub(toFraction: $0) }
                    ),
                    in: 0 ... 1
                ) { editing in
                    if editing {
                        scrubFraction = viewModel.progress // 値変更なしで終了しても現在位置へ（stale 防止）
                        viewModel.beginScrubbing()
                    } else {
                        viewModel.endScrubbing(atFraction: scrubFraction)
                    }
                }
                .tint(ReverbTheme.Palette.accent)
                .accessibilityLabel("再生位置")
                .accessibilityValue("\(viewModel.currentTimecode) / \(viewModel.durationTimecode)")

                Text(viewModel.durationTimecode)
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 52, alignment: .trailing)
            }

            HStack(spacing: 18) {
                playPauseButton
                Spacer()
                subtitleToggleButton
                fullscreenButton
            }
        }
    }

    private var playPauseButton: some View {
        Button {
            viewModel.togglePlayPause()
        } label: {
            Image(systemName: viewModel.isPlaying ? "pause.fill" : "play.fill")
                .imageScale(.large)
                .frame(width: ReverbTheme.Metrics.primaryHitTarget, height: ReverbTheme.Metrics.primaryHitTarget)
        }
        .buttonStyle(.borderless)
        .keyboardShortcut(.space, modifiers: [])
        .accessibilityLabel(viewModel.isPlaying ? "一時停止" : "再生")
    }

    private var subtitleToggleButton: some View {
        Button {
            viewModel.toggleSubtitles()
        } label: {
            Label(
                viewModel.subtitlesEnabled ? "字幕 ON" : "字幕 OFF",
                systemImage: viewModel.subtitlesEnabled ? "captions.bubble.fill" : "captions.bubble"
            )
        }
        .buttonStyle(.borderless)
        .accessibilityLabel("字幕表示")
        .accessibilityValue(viewModel.subtitlesEnabled ? "オン" : "オフ")
        .accessibilityHint("字幕の表示だけを切り替えます。音声や再生位置は変わりません")
    }

    private var fullscreenButton: some View {
        Button {
            toggleFullScreen()
        } label: {
            Label("フルスクリーン", systemImage: "arrow.up.left.and.arrow.down.right")
        }
        .buttonStyle(.borderless)
        .accessibilityLabel("フルスクリーン")
    }

    /// ネイティブ・フルスクリーンを切り替える（USL-90）。
    /// ホスト中のウィンドウを優先し、取れなければ key/main/可視ウィンドウへフォールバックする。
    /// アクセサリ起動などで `.fullScreenPrimary` が欠ける場合に備え、呼ぶ前に必ず挿入する。
    private func toggleFullScreen() {
        guard let window = hostingWindow
            ?? NSApp.keyWindow
            ?? NSApp.mainWindow
            ?? NSApp.windows.first(where: { $0.isVisible })
        else { return }
        window.collectionBehavior.insert(.fullScreenPrimary)
        window.toggleFullScreen(nil)
    }

    // MARK: - 下段（オーディオバランス）

    /// 再生段階では全工程が完了済みで「完了した工程」一覧は固定表示にすぎず情報価値がないため非表示
    /// （USL-101）。下段はオーディオバランスのみを左寄せで置き、全幅への間延びを抑える。
    private var bottomPanels: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("オーディオバランス")
                .font(.title3.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            AudioBalanceControl(
                japaneseVolume: Binding(
                    get: { viewModel.japaneseVolume },
                    set: { viewModel.setJapaneseVolume($0) }
                ),
                originalVolume: Binding(
                    get: { viewModel.originalVolume },
                    set: { viewModel.setOriginalVolume($0) }
                )
            )
        }
        .frame(maxWidth: 560, alignment: .leading)
    }

    // MARK: - 共通の通知カード

    private func noticeCard(
        systemImage: String,
        role: StatusRole,
        title: String,
        message: String,
        primary: (String, () -> Void)
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label {
                Text(title).font(.title3.weight(.semibold))
            } icon: {
                Image(systemName: systemImage).foregroundStyle(role.color)
            }
            Text(message)
                .font(.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button(primary.0, action: primary.1)
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
        }
        .padding(20)
        .frame(maxWidth: 560, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(ReverbTheme.Palette.underPageBackground)
        )
        .accessibilityElement(children: .combine)
    }
}

// MARK: - 動画面（AVKit）

/// AVKit の動画面。標準トランスポートは出さず（`.none`）、コントロールは自前で提供する（§5.3）。
private struct VideoSurface: NSViewRepresentable {
    let player: AVPlayer

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .none
        view.videoGravity = .resizeAspect
        view.player = player
        return view
    }

    func updateNSView(_ nsView: AVPlayerView, context: Context) {
        if nsView.player !== player {
            nsView.player = player
        }
    }
}
