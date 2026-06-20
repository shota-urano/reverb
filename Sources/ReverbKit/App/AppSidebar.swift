import SwiftUI

/// アプリ左ペイン（design-system §5.1）。
/// 上から: ロゴ＋アプリ名 → ライブラリ/処理中/設定 → 区切り線 → 最近のプロジェクト → 下端 LocalOnlyStatus。
public struct AppSidebar: View {
    @Bindable private var model: AppModel

    public init(model: AppModel) {
        self.model = model
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            // 主ナビゲーション。選択行はアクセントの淡い背景＋左端バーで示す（List 標準選択で表現）。
            List(selection: $model.selection) {
                ForEach(SidebarSection.allCases) { section in
                    Label(section.title, systemImage: section.systemImage)
                        .tag(section)
                }

                Section("最近のプロジェクト") {
                    if model.recentProjects.isEmpty {
                        Text("まだありません")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(model.recentProjects) { project in
                            // キーボード操作・VoiceOver に対応するため Button で活性化する（§7）。
                            Button {
                                model.open(project)
                            } label: {
                                RecentProjectRow(project: project)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .listStyle(.sidebar)

            Divider()
            footer
        }
        .frame(minWidth: 220, idealWidth: 230, maxWidth: 280) // §1: サイドバー 230pt（220〜280）
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: "waveform.circle.fill")
                .font(.title2)
                .foregroundStyle(Color.accentColor)
            Text("Reverb")
                .font(.title3.weight(.semibold))
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.top, 16)
        .padding(.bottom, 8)
    }

    private var footer: some View {
        // 依存エンジン異常時は緑を使わず、クリックで設定（依存状態）へ誘導する。
        LocalOnlyStatus(
            healthy: model.health?.dependencies.allAvailable ?? false,
            action: model.health?.dependencies.allAvailable == true
                ? nil
                : { model.selection = .settings }
        )
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }
}

/// 最近のプロジェクト1行（サムネイル・タイトル・日時の3要素 / §5.1）。
private struct RecentProjectRow: View {
    let project: RecentProject

    var body: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 8) // サムネイル角丸 8pt（§4）
                .fill(Color.black.opacity(0.85))
                .aspectRatio(16.0 / 9.0, contentMode: .fit)
                .frame(width: 48)
                .overlay(Image(systemName: "film").foregroundStyle(.white.opacity(0.5)).imageScale(.small))
            VStack(alignment: .leading, spacing: 2) {
                Text(project.title)
                    .font(.body.weight(.medium))
                    .lineLimit(1)
                Text(project.updatedAt, style: .date)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}
