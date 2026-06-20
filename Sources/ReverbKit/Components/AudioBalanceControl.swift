import SwiftUI

/// オーディオバランス（design-system §5.5 / screens.md §3「オーディオ」）。
///
/// `日本語` と `元音声` を独立スライダーで調整する。**初期値は必ず 100% / 8%**
/// （`MixSettings.confirmedInitial`・ルール4）だが、初期値の設定は呼び出し側の責務。
/// 本コントロールは束縛された値の編集と常時の数値表示・アクセシビリティのみを担う。
public struct AudioBalanceControl: View {
    @Binding private var japaneseVolume: Double
    @Binding private var originalVolume: Double

    public init(japaneseVolume: Binding<Double>, originalVolume: Binding<Double>) {
        self._japaneseVolume = japaneseVolume
        self._originalVolume = originalVolume
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: ReverbTheme.Metrics.elementSpacing) {
            volumeSlider(
                label: "日本語",
                systemImage: "speaker.wave.2",
                value: $japaneseVolume
            )
            volumeSlider(
                label: "元音声",
                systemImage: "speaker.wave.1",
                value: $originalVolume
            )
        }
    }

    private func volumeSlider(
        label: String,
        systemImage: String,
        value: Binding<Double>
    ) -> some View {
        HStack(spacing: 12) {
            Label(label, systemImage: systemImage)
                .labelStyle(.titleAndIcon)
                .font(.body)
                .frame(width: 96, alignment: .leading)

            // macOS の Slider はキーボード操作に対応。VoiceOver には調整値を読み上げる（§5.5/§7）。
            Slider(value: value, in: 0 ... 1)
                .tint(ReverbTheme.Palette.accent)
                .accessibilityLabel(label)
                .accessibilityValue(ReverbFormat.percent(value.wrappedValue))

            // 数値をスライダーの近くへ常時表示（§5.5）。
            Text(ReverbFormat.percent(value.wrappedValue))
                .font(.body.monospacedDigit())
                .frame(width: 52, alignment: .trailing)
                .accessibilityHidden(true)
        }
    }
}
