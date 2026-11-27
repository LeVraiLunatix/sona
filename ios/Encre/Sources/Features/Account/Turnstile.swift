import SwiftUI
import WebKit

/// Anti-robot Cloudflare Turnstile : Supabase l'exige pour les connexions par e-mail. La page est déclarée à
/// l'adresse du site, la seule autorisée pour cette clé.
struct Turnstile: UIViewRepresentable {
    @Binding var token: String

    /// Clé de site PUBLIQUE, la même que dans web/index.html.
    private static let html = """
    <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>html,body{margin:0;background:transparent}</style>
    <script>function send(t){window.webkit.messageHandlers.turnstile.postMessage(typeof t==="string"?t:"")}
    function clear(){send("")}</script>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
    <div class="cf-turnstile" data-sitekey="0x4AAAAAAGUqT48G36H5nVLg" data-theme="dark" data-size="flexible"
         data-callback="send" data-expired-callback="clear" data-error-callback="clear"></div>
    """

    func makeCoordinator() -> Coordinator { Coordinator(token: $token) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(context.coordinator, name: "turnstile")
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isOpaque = false
        view.backgroundColor = .clear
        view.scrollView.backgroundColor = .clear
        view.scrollView.isScrollEnabled = false
        view.loadHTMLString(Self.html, baseURL: URL(string: "https://www.trysona.fr"))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "turnstile")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        private let token: Binding<String>
        init(token: Binding<String>) { self.token = token }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            // Un jeton expiré ou une erreur arrivent vides : le bouton se re-désactive.
            token.wrappedValue = message.body as? String ?? ""
        }
    }
}
