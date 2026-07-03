import Testing
import Foundation
@testable import ReverbKit

/// サイドカー起動コマンドの解決（env 上書き / 同梱バンドル）を検証する。
/// 配布 .app では env 未設定でもバンドル相対で python/main.py を解決できること、
/// 未配置なら nil を返して「黙って成功しない」ことを担保する（§3.1・ルール6）。
@Suite struct SidecarConfigurationTests {

    @Test func fromEnvironmentResolvesExecutableAndArgs() {
        let env = [
            "REVERB_BACKEND_EXECUTABLE": "/usr/bin/python3",
            "REVERB_BACKEND_ARGS": "/tmp/main.py --flag",
        ]
        let config = SidecarConfiguration.fromEnvironment(env)
        #expect(config?.executableURL.path == "/usr/bin/python3")
        #expect(config?.arguments == ["/tmp/main.py", "--flag"])
    }

    @Test func fromEnvironmentReturnsNilWhenUnset() {
        #expect(SidecarConfiguration.fromEnvironment([:]) == nil)
    }

    @Test func fromBundleReturnsNilWhenRuntimeMissing() throws {
        let bundle = try makeBundle(withRuntime: false)
        defer { try? FileManager.default.removeItem(at: bundle.bundleURL) }
        #expect(SidecarConfiguration.fromBundle(bundle, environment: [:]) == nil)
    }

    @Test func fromBundleResolvesEmbeddedRuntime() throws {
        let bundle = try makeBundle(withRuntime: true)
        defer { try? FileManager.default.removeItem(at: bundle.bundleURL) }
        let resources = bundle.resourceURL!

        let config = try #require(SidecarConfiguration.fromBundle(bundle, environment: [:]))
        #expect(config.executableURL.path
            == resources.appendingPathComponent("python-runtime/bin/python3").path)
        #expect(config.arguments == [resources.appendingPathComponent("backend/main.py").path])
        // 同梱 ffmpeg/ffprobe とバックエンド import 起点が環境変数で渡ること。
        #expect(config.environment?["REVERB_FFMPEG_BIN"]
            == resources.appendingPathComponent("bin/ffmpeg").path)
        #expect(config.environment?["REVERB_FFPROBE_BIN"]
            == resources.appendingPathComponent("bin/ffprobe").path)
        #expect(config.environment?["PYTHONPATH"]
            == resources.appendingPathComponent("backend").path)
    }

    /// テスト用に最小のバンドル構造（Contents/Info.plist + Resources）を一時生成する。
    /// `withRuntime` が true のときだけ python-runtime/bin/python3 と backend/main.py を置く。
    private func makeBundle(withRuntime: Bool) throws -> Bundle {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory
            .appendingPathComponent("ReverbBundleTest-\(UUID().uuidString).bundle")
        let resources = root.appendingPathComponent("Contents/Resources")
        try fileManager.createDirectory(at: resources, withIntermediateDirectories: true)
        // Contents/Info.plist があると Bundle は resourceURL を Contents/Resources に解決する。
        try Data("{}".utf8).write(
            to: root.appendingPathComponent("Contents/Info.plist"))

        if withRuntime {
            let python = resources.appendingPathComponent("python-runtime/bin/python3")
            let mainScript = resources.appendingPathComponent("backend/main.py")
            try fileManager.createDirectory(
                at: python.deletingLastPathComponent(), withIntermediateDirectories: true)
            try fileManager.createDirectory(
                at: mainScript.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data().write(to: python)
            try Data().write(to: mainScript)
        }
        return try #require(Bundle(url: root))
    }
}
