import SwiftUI

/// 各画面共通の外枠（design-system §1: 外周余白32pt / タイトル .largeTitle）。
/// 画面タイトル → 内容の順で VoiceOver 読み上げ順を整える（§7）。
struct ScreenScaffold<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 28) { // §1: セクション間隔 28〜32pt
            Text(title)
                .font(.largeTitle.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            content
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(32)
    }
}

/// 未実装画面の暫定表示。担当 issue を明示する（土台のみ / USL-75）。
struct PlaceholderNote: View {
    let issue: String
    let detail: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "hammer")
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text("この画面は \(issue) で実装します")
                    .font(.body.weight(.medium))
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(nsColor: .underPageBackgroundColor))
        )
    }
}
