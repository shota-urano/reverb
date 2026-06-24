import SwiftUI

/// ゆっくり回る不確定スピナー。
///
/// ネイティブの `ProgressView()`（円形）は回転速度を制御できないため、処理中の
/// 「くるくる」を落ち着いた速度で回したい箇所はこれに差し替える。
///
/// 回転は `TimelineView(.animation)` で時刻から角度を直接算出する。`onAppear` +
/// `repeatForever` の暗黙アニメーションは macOS で発火しないことがあるため、表示
/// リフレッシュに同期して毎フレーム再描画するこの方式を採る。`period` が1回転の
/// 秒数（大きいほどゆっくり）。
public struct SlowSpinner: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let size: CGFloat
    private let lineWidth: CGFloat
    private let period: Double

    public init(size: CGFloat = 16, lineWidth: CGFloat = 2, period: Double = 2.6) {
        self.size = size
        self.lineWidth = lineWidth
        self.period = period
    }

    public var body: some View {
        Group {
            if reduceMotion {
                // Reduce Motion 時は回さず静止（§7）。進捗の意味は周辺テキスト/値が担う。
                arc(angle: 0)
            } else {
                TimelineView(.animation) { context in
                    let t = context.date.timeIntervalSinceReferenceDate
                    let angle = (t.truncatingRemainder(dividingBy: period) / period) * 360.0
                    arc(angle: angle)
                }
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true) // 進捗の意味は周辺テキスト/値が担う
    }

    private func arc(angle: Double) -> some View {
        Circle()
            .trim(from: 0, to: 0.72)
            .stroke(style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
            .foregroundStyle(.secondary)
            .frame(width: size, height: size)
            .rotationEffect(.degrees(angle))
    }
}
