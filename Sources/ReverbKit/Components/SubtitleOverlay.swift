import SwiftUI

/// 字幕オーバーレイ（design-system §5.6 / screens.md §3「字幕」）。
///
/// `subtitles.json` の `lines` を**そのまま表示し、UI で再分割しない**。最大2行。
/// 画面下部中央に置く想定で、背景帯は文字幅に合わせて左右24〜32pt・上下10〜14ptの余白を取る。
/// 配置（下端からの距離・再生コントロールとの間隔）は呼び出し側の画面が決める。
public struct SubtitleOverlay: View {
    private let lines: [String]

    public init(lines: [String]) {
        self.lines = lines
    }

    public var body: some View {
        if lines.isEmpty {
            EmptyView()
        } else {
            VStack(spacing: 2) {
                // 最大2行。3行目を作らない（§5.6 / screens §3）。再分割はしない。
                ForEach(Array(lines.prefix(2).enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6) // 幅不足時はフォントを許容範囲で縮小（screens §3）
                }
            }
            .font(.title2.weight(.medium)) // 字幕タイポ（§3）
            .foregroundStyle(.white)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 28) // 24〜32pt
            .padding(.vertical, 12)   // 10〜14pt
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(ReverbTheme.Palette.subtitleScrim)
            )
            .accessibilityElement(children: .combine)
            .accessibilityLabel(lines.prefix(2).joined(separator: " "))
        }
    }
}
