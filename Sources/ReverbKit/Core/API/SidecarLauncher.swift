import Foundation
import Darwin // kill(2) / SIGKILL

/// サイドカー（Python バックエンド）の子プロセス起動・監視・終了を担う境界（01-architecture §3）。
/// テスト時はモックに差し替えられるよう protocol で切る（実プロセスを起動しない）。
public protocol SidecarLauncher: Sendable {
    /// バックエンドを起動し、標準出力のハンドシェイクを受領して baseURL を確定する。
    /// `onTerminate` は子プロセスが予期せず終了したとき終了コードと共に呼ばれる（生存監視）。
    func launch(onTerminate: @escaping @Sendable (Int32) -> Void) async throws -> ReadyHandshake
    /// 子プロセスを終了する（タイムアウト時は強制終了）。
    func terminate() async
}

/// サイドカー起動設定。ホスト・ポートはハンドシェイクで受け取るためここには持たない（§3.1）。
public struct SidecarConfiguration: Sendable, Equatable {
    public var executableURL: URL
    public var arguments: [String]
    public var environment: [String: String]?
    /// ハンドシェイク受領のタイムアウト（秒）。
    public var handshakeTimeout: Duration

    public init(
        executableURL: URL,
        arguments: [String] = [],
        environment: [String: String]? = nil,
        handshakeTimeout: Duration = .seconds(30)
    ) {
        self.executableURL = executableURL
        self.arguments = arguments
        self.environment = environment
        self.handshakeTimeout = handshakeTimeout
    }

    /// 環境変数からサイドカー起動コマンドを解決する。
    /// `REVERB_BACKEND_EXECUTABLE`（必須）/ `REVERB_BACKEND_ARGS`（空白区切り・任意）。
    /// パスをコードに固定しないための解決手段（ルール6・§3.1）。
    public static func fromEnvironment(
        _ environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> SidecarConfiguration? {
        guard let exec = environment["REVERB_BACKEND_EXECUTABLE"], !exec.isEmpty else {
            return nil
        }
        let args = environment["REVERB_BACKEND_ARGS"]?
            .split(separator: " ")
            .map(String.init) ?? []
        return SidecarConfiguration(
            executableURL: URL(fileURLWithPath: exec),
            arguments: args
        )
    }
}

public enum SidecarError: Error, Sendable, Equatable {
    /// 起動コマンドが未設定（バンドル同梱パス or 環境変数で指定する）。
    case notConfigured
    /// プロセス起動に失敗。
    case launchFailed(String)
    /// ハンドシェイクが時間内に得られなかった。
    case handshakeTimeout
    /// 標準出力が途中で閉じられハンドシェイクを得られなかった。
    case handshakeUnavailable
    /// ハンドシェイク行を解釈できなかった。
    case invalidHandshake(String)
}

/// `Process` を用いた実サイドカー起動実装。
///
/// 親プロセス（Swift）消失時の自死はバックエンド側責務（§3.2）。こちらは予期せぬ
/// 終了を `onTerminate` で通知し、`terminate()` で安全停止する。
public actor ProcessSidecarLauncher: SidecarLauncher {
    private let configuration: SidecarConfiguration
    private var process: Process?
    /// ハンドシェイク後の stdout 読み捨てタスク（pipe 詰まり防止）。
    private var drainTask: Task<Void, Never>?

    public init(configuration: SidecarConfiguration) {
        self.configuration = configuration
    }

    public func launch(onTerminate: @escaping @Sendable (Int32) -> Void) async throws -> ReadyHandshake {
        let process = Process()
        process.executableURL = configuration.executableURL
        process.arguments = configuration.arguments
        if let environment = configuration.environment {
            process.environment = environment
        }

        let stdoutPipe = Pipe()
        process.standardOutput = stdoutPipe

        // 予期せぬ終了の監視（§3.2）。
        process.terminationHandler = { proc in
            onTerminate(proc.terminationStatus)
        }

        do {
            try process.run()
        } catch {
            throw SidecarError.launchFailed(error.localizedDescription)
        }
        self.process = process

        let handle = stdoutPipe.fileHandleForReading
        do {
            // 標準出力からハンドシェイク行を待つ（タイムアウト付き）。
            let handshake = try await withThrowingTaskGroup(of: ReadyHandshake.self) { group in
                let timeout = configuration.handshakeTimeout
                group.addTask {
                    try await Self.readHandshake(from: handle)
                }
                group.addTask {
                    try await Task.sleep(for: timeout)
                    throw SidecarError.handshakeTimeout
                }
                guard let handshake = try await group.next() else {
                    throw SidecarError.handshakeUnavailable
                }
                group.cancelAll()
                return handshake
            }
            // 以降、誰も stdout を読まないとバッファが埋まりバックエンドの write が
            // ブロックする（pipe deadlock）。読み捨てタスクを常駐させて防ぐ。
            drainTask = Task {
                do {
                    for try await _ in handle.bytes {
                        if Task.isCancelled { break }
                    }
                } catch {
                    // 読み取り終了・キャンセルは想定内。
                }
            }
            return handshake
        } catch {
            // 起動応答が得られなかった場合は子プロセスを残さない（孤児・多重起動防止）。
            process.terminationHandler = nil
            if process.isRunning { process.terminate() }
            self.process = nil
            throw error
        }
    }

    public func terminate() async {
        drainTask?.cancel()
        drainTask = nil
        guard let process, process.isRunning else {
            self.process = nil
            return
        }
        // terminationHandler による予期せぬ終了通知を抑止してから停止する。
        process.terminationHandler = nil
        process.terminate() // SIGTERM
        // 子が SIGTERM を無視する場合に備え、猶予後に SIGKILL で強制終了する（§3.2 の契約）。
        let deadline = ContinuousClock.now + .seconds(5)
        while process.isRunning && ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(100))
        }
        if process.isRunning {
            _ = Darwin.kill(process.processIdentifier, SIGKILL)
        }
        self.process = nil
    }

    /// 標準出力を 1 行ずつ読み、最初の `{"event":"ready",...}` を解釈する。
    private static func readHandshake(from handle: FileHandle) async throws -> ReadyHandshake {
        let decoder = JSONDecoder()
        for try await line in handle.bytes.lines {
            guard let data = line.data(using: .utf8), line.contains("\"event\"") else {
                continue
            }
            guard let handshake = try? decoder.decode(ReadyHandshake.self, from: data),
                  handshake.event == "ready" else {
                continue
            }
            return handshake
        }
        throw SidecarError.handshakeUnavailable
    }
}
