import SwiftUI

/// Mots cherchés mis en évidence dans un texte (sans tenir compte des accents ni de la casse).
enum Highlight {
    static func attributed(_ text: String, query: String) -> AttributedString {
        let words = query.folded.split(separator: " ").map { Array($0) }.filter { $0.count >= 2 }
        guard !words.isEmpty else { return AttributedString(text) }

        // Texte aplati (un caractère plié par case) et, pour chaque case, le caractère d'origine.
        let chars = Array(text)
        var flat: [Character] = []
        var owner: [Int] = []
        for (index, char) in chars.enumerated() {
            for folded in String(char).folded {
                flat.append(folded)
                owner.append(index)
            }
        }

        var marked = Set<Int>()
        for word in words where flat.count >= word.count {
            var start = 0
            while start + word.count <= flat.count {
                if Array(flat[start..<(start + word.count)]) == word {
                    for j in start..<(start + word.count) { marked.insert(owner[j]) }
                    start += word.count
                } else {
                    start += 1
                }
            }
        }
        guard !marked.isEmpty else { return AttributedString(text) }

        var out = AttributedString()
        var run: [Character] = []
        var runMarked = false
        func flush() {
            guard !run.isEmpty else { return }
            var piece = AttributedString(String(run))
            if runMarked { piece.backgroundColor = Color.white.opacity(0.22) }
            out += piece
            run = []
        }
        for (index, char) in chars.enumerated() {
            let isMarked = marked.contains(index)
            if isMarked != runMarked { flush(); runMarked = isMarked }
            run.append(char)
        }
        flush()
        return out
    }
}

/// Texte de ligne : surligné quand `highlight` n'est pas vide, sinon un `Text` ordinaire.
struct HighlightedText: View {
    let text: String
    var highlight = ""

    var body: some View {
        if highlight.trimmingCharacters(in: .whitespaces).isEmpty {
            Text(text)
        } else {
            Text(Highlight.attributed(text, query: highlight))
        }
    }
}

/// Squelette de la recherche : des lignes grisées qui pulsent en attendant les résultats.
struct SearchSkeleton: View {
    @State private var pulse = false

    var body: some View {
        VStack(alignment: .leading, spacing: 26) {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Tone.surface)
                .frame(height: 120)
            VStack(alignment: .leading, spacing: 16) {
                ForEach(0..<6, id: \.self) { index in
                    HStack(spacing: 14) {
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(Tone.surface)
                            .frame(width: 50, height: 50)
                        VStack(alignment: .leading, spacing: 8) {
                            Capsule().fill(Tone.surface).frame(width: 150 + CGFloat(index % 3) * 40, height: 12)
                            Capsule().fill(Tone.surface).frame(width: 90 + CGFloat(index % 2) * 30, height: 10)
                        }
                        Spacer(minLength: 0)
                    }
                }
            }
        }
        .padding(.horizontal, 20)
        .opacity(pulse ? 0.45 : 1)
        .onAppear {
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) { pulse = true }
        }
        .accessibilityHidden(true)
    }
}
