import SwiftUI

/// Pochette d'un morceau/album/artiste : l'image distante si l'API en fournit
/// une (Deezer/Apple/Spotify en ont presque toujours), sinon un aplat de
/// formes superposées en mode "multiply" — écho du placeholder CMJN du
/// prototype (`Cover.dc.html`) pour les rares cas sans pochette.
struct CoverArt: View {
    let url: String?
    let title: String
    var cornerRadius: CGFloat = 6

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                if let url, let imageURL = URL(string: url) {
                    AsyncImage(url: imageURL) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().scaledToFill()
                        default:
                            placeholder(size: proxy.size)
                        }
                    }
                } else {
                    placeholder(size: proxy.size)
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
    }

    private func placeholder(size: CGSize) -> some View {
        let seed = abs(title.hashValue)
        let colors = [EncreColor.accent, EncreColor.accent2, EncreColor.processYellow]
        return ZStack {
            EncreColor.surface
            ForEach(0..<2, id: \.self) { i in
                let c = colors[(seed + i) % colors.count]
                Circle()
                    .fill(c)
                    .blendMode(.multiply)
                    .frame(width: size.width * 0.7, height: size.width * 0.7)
                    .offset(
                        x: CGFloat((seed >> (i * 3)) % 40 - 20),
                        y: CGFloat((seed >> (i * 5)) % 40 - 20)
                    )
            }
            Text(title.first.map(String.init) ?? "?")
                .font(EncreFont.heading(size.height * 0.5))
                .foregroundStyle(EncreColor.text)
                .blendMode(.multiply)
        }
        .compositingGroup()
    }
}
