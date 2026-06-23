import SwiftUI
import AppKit

/// SwiftUI View からホスト中の `NSWindow` を取り出すためのアクセサ（USL-90）。
///
/// `NSApp.keyWindow` 単独依存だと状況により nil になり無音 no-op を招くため、実際にこの View を
/// 載せているウィンドウを確実に得る用途で使う。背景レイヤに敷いて利用する。
struct WindowAccessor: NSViewRepresentable {
    /// 解決したウィンドウ（未解決時は nil）を通知するクロージャ。
    let onResolve: (NSWindow?) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        // view がウィンドウ階層に載るのを待ってから解決する。
        DispatchQueue.main.async { [weak view] in onResolve(view?.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { [weak nsView] in onResolve(nsView?.window) }
    }
}
