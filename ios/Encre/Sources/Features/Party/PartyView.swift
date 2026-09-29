import SwiftUI

/// « Écoute ensemble » : lancer ou rejoindre une session, puis la salle —
/// code à partager, qui est là, titre en cours, réactions qui s'envolent,
/// propositions de titres.
struct PartyView: View {
    @ObservedObject private var party = PartyManager.shared
    @EnvironmentObject private var player: PlayerManager
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if let state = party.state {
                    PartyRoom(state: state)
                } else {
                    PartyLobby()
                }
            }
            .background(Tone.background)
            .navigationTitle("Écoute ensemble")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Fermer") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Avant la session

private struct PartyLobby: View {
    @ObservedObject private var party = PartyManager.shared
    @State private var code = ""
    @State private var active: [PartySummary] = []
    @State private var working = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                VStack(alignment: .leading, spacing: 10) {
                    Image(systemName: "person.2.wave.2.fill")
                        .font(.system(size: 40, weight: .semibold))
                        .foregroundStyle(Tone.primary)
                        .symbolEffect(.variableColor.iterative, options: .repeating)
                    Text("Le même son, au même moment")
                        .font(.system(size: 26, weight: .bold))
                        .foregroundStyle(Tone.primary)
                    Text("Lance une session et partage le code : tes amis entendent exactement ce que tu joues, chacun sur son téléphone, où qu'ils soient.")
                        .font(Typo.body)
                        .foregroundStyle(Tone.secondary)
                }

                PillButton(title: "Lancer une session", systemImage: "dot.radiowaves.left.and.right", isLoading: working) {
                    Task {
                        working = true
                        await party.create()
                        working = false
                    }
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("Rejoindre avec un code").font(Typo.headline).foregroundStyle(Tone.primary)
                    HStack(spacing: 10) {
                        TextField("ABCDE", text: $code)
                            .font(.system(size: 24, weight: .bold, design: .monospaced))
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .foregroundStyle(Tone.primary)
                            .padding(.horizontal, 16)
                            .frame(height: 54)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
                            .onChange(of: code) { _, value in code = String(value.uppercased().prefix(5)) }
                        Button {
                            Task { await party.join(code: code) }
                        } label: {
                            Image(systemName: "arrow.right")
                                .font(.system(size: 20, weight: .bold))
                                .foregroundStyle(.black)
                                .frame(width: 54, height: 54)
                                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white))
                        }
                        .buttonStyle(.pressable(scale: 0.9))
                        .disabled(code.count != 5)
                        .opacity(code.count == 5 ? 1 : 0.4)
                    }
                }

                if !active.filter({ !$0.joined }).isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Sessions de tes amis").font(Typo.headline).foregroundStyle(Tone.primary)
                        ForEach(active.filter { !$0.joined }) { summary in
                            PartySummaryRow(summary: summary) {
                                Task { await party.join(code: summary.code) }
                            }
                        }
                    }
                }

                if let error = party.errorMessage {
                    Text(error).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
            }
            .padding(20)
        }
        .task {
            while !Task.isCancelled {
                active = (try? await APIClient.shared.activeParties()) ?? active
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }
}

struct PartySummaryRow: View {
    let summary: PartySummary
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                ZStack {
                    Artwork(url: summary.track?.coverURL ?? summary.hostAvatarURL, cornerRadius: 12, symbol: "person.2.fill")
                    Color.black.opacity(0.3).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    EqualizerBars(isAnimating: true).frame(width: 16, height: 14)
                }
                .frame(width: 56, height: 56)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Session de \(summary.hostName ?? "?")").font(Typo.rowTitle).foregroundStyle(Tone.primary)
                    Text(summary.track.map { "\($0.title) · \($0.artist)" } ?? "Pas encore de titre")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                        .lineLimit(1)
                    Text("\(summary.members) à l'écoute").font(Typo.caption).foregroundStyle(Tone.tertiary)
                }
                Spacer()
                Text("Rejoindre")
                    .font(Typo.caption)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Capsule().fill(.white))
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surface))
        }
        .buttonStyle(.pressable(scale: 0.98))
    }
}

// MARK: - Dans la session

private struct PartyRoom: View {
    let state: PartyState
    @ObservedObject private var party = PartyManager.shared
    @EnvironmentObject private var player: PlayerManager
    @State private var floating: [FloatingReaction] = []
    @State private var query = ""
    @State private var results: [Track] = []
    @State private var searching = false

    private let emojis = ["🔥", "😍", "💃", "😭", "🤯", "👏"]

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    codeCard
                    members
                    nowPlaying
                    reactionBar
                    if !state.isHost { proposeSection }
                    if !state.queue.isEmpty { proposals }
                    Button(role: .destructive) {
                        Task { await party.leave() }
                    } label: {
                        Text(state.isHost ? "Arrêter la session" : "Quitter la session")
                            .font(Typo.headline)
                            .foregroundStyle(Tone.danger)
                            .frame(maxWidth: .infinity)
                            .frame(height: 50)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surface))
                    }
                    .buttonStyle(.pressable)
                }
                .padding(20)
                .padding(.bottom, 40)
            }
            // Réactions qui s'envolent depuis le bas de l'écran.
            ForEach(floating) { reaction in
                FloatingEmoji(reaction: reaction)
            }
        }
        .onChange(of: party.freshReactions) { _, new in
            for reaction in new {
                floating.append(FloatingReaction(emoji: reaction.emoji, by: reaction.by))
            }
            let count = floating.count
            if count > 20 { floating.removeFirst(count - 20) }
        }
    }

    private var codeCard: some View {
        VStack(spacing: 10) {
            Text(state.isHost ? "TA SESSION" : "SESSION DE \((state.hostName ?? "").uppercased())")
                .font(Typo.caption).tracking(1.5).foregroundStyle(Tone.secondary)
            Text(state.code)
                .font(.system(size: 46, weight: .heavy, design: .monospaced))
                .foregroundStyle(Tone.primary)
                .tracking(6)
            ShareLink(item: "Rejoins mon écoute sur Sona : Amis › Écoute ensemble › code \(state.code)") {
                Label("Inviter", systemImage: "square.and.arrow.up")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.primary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(Capsule().fill(Tone.surfaceStrong))
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 22)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.35, green: 0.2, blue: 0.9).opacity(0.55), Tone.surface],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
        )
    }

    private var members: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("\(state.members.count) à l'écoute").font(Typo.headline).foregroundStyle(Tone.primary)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 14) {
                    ForEach(state.members, id: \.name) { member in
                        VStack(spacing: 6) {
                            ZStack(alignment: .bottomTrailing) {
                                Artwork(url: member.avatarURL, cornerRadius: 26, symbol: "person.fill")
                                    .frame(width: 52, height: 52)
                                if member.isHost {
                                    Image(systemName: "crown.fill")
                                        .font(.system(size: 10, weight: .bold))
                                        .foregroundStyle(.black)
                                        .padding(4)
                                        .background(Circle().fill(Color.yellow))
                                }
                            }
                            Text(member.name).font(Typo.caption).foregroundStyle(Tone.secondary).lineLimit(1)
                        }
                        .frame(width: 64)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var nowPlaying: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let track = state.track {
                HStack(spacing: 14) {
                    Artwork(url: track.coverURL, cornerRadius: 12).frame(width: 76, height: 76)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 6) {
                            if !state.paused { EqualizerBars(isAnimating: true).frame(width: 12, height: 11) }
                            Text(state.paused ? "EN PAUSE" : "EN CE MOMENT")
                                .font(Typo.caption).tracking(1.2).foregroundStyle(Tone.secondary)
                        }
                        Text(track.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                        Text(track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                }
                if !state.isHost {
                    let synced = player.current?.id == track.id && abs(party.driftSeconds) <= 2.5
                    Label(synced ? "Synchronisé avec \(state.hostName ?? "l'hôte")" : "Synchronisation…",
                          systemImage: synced ? "checkmark.circle.fill" : "arrow.triangle.2.circlepath")
                        .font(Typo.caption)
                        .foregroundStyle(synced ? Color.green : Tone.secondary)
                }
            } else {
                Text(state.isHost
                     ? "Lance n'importe quel titre (recherche, playlist, radio…) : tout le monde l'entend en même temps."
                     : "En attente du premier titre de \(state.hostName ?? "l'hôte")…")
                    .font(Typo.body)
                    .foregroundStyle(Tone.secondary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
    }

    private var reactionBar: some View {
        HStack {
            ForEach(emojis, id: \.self) { emoji in
                Button {
                    floating.append(FloatingReaction(emoji: emoji, by: "Toi"))
                    Task { await party.react(emoji) }
                } label: {
                    Text(emoji).font(.system(size: 30))
                        .frame(maxWidth: .infinity)
                        .frame(height: 52)
                        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surface))
                }
                .buttonStyle(.pressable(scale: 0.8))
                .sensoryFeedback(.impact(weight: .light), trigger: floating.count)
            }
        }
    }

    private var proposeSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Proposer un titre").font(Typo.headline).foregroundStyle(Tone.primary)
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(Tone.tertiary)
                TextField("Titre, artiste…", text: $query)
                    .foregroundStyle(Tone.primary)
                    .submitLabel(.search)
                    .onSubmit { Task { await search() } }
                if searching { ProgressView().tint(.white) }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Tone.surfaceStrong))
            ForEach(results.prefix(6)) { track in
                HStack(spacing: 12) {
                    Artwork(url: track.coverURL, cornerRadius: 6).frame(width: 44, height: 44)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                        Text(track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                    Spacer()
                    Button {
                        Task {
                            await party.propose(track)
                            results.removeAll { $0.id == track.id }
                        }
                    } label: {
                        Image(systemName: "plus.circle.fill").font(.system(size: 26)).foregroundStyle(Tone.primary)
                    }
                    .buttonStyle(.pressable(scale: 0.85))
                }
            }
        }
    }

    private var proposals: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Proposés").font(Typo.headline).foregroundStyle(Tone.primary)
            ForEach(state.queue) { item in
                HStack(spacing: 12) {
                    Artwork(url: item.track.coverURL, cornerRadius: 6).frame(width: 40, height: 40)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                        Text("par \(item.by)").font(Typo.caption).foregroundStyle(Tone.secondary)
                    }
                }
            }
        }
    }

    private func search() async {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        searching = true
        results = (try? await APIClient.shared.search(query: text).tracks) ?? []
        searching = false
    }
}

struct FloatingReaction: Identifiable, Equatable {
    let id = UUID()
    let emoji: String
    let by: String
}

/// Emoji qui monte en ondulant puis s'efface.
private struct FloatingEmoji: View {
    let reaction: FloatingReaction
    @State private var rise = false
    @State private var drift = CGFloat.random(in: -120...120)

    var body: some View {
        VStack(spacing: 2) {
            Text(reaction.emoji).font(.system(size: 44))
            Text(reaction.by).font(Typo.caption).foregroundStyle(Tone.secondary)
        }
        .offset(x: rise ? drift : drift * 0.2, y: rise ? -520 : 0)
        .opacity(rise ? 0 : 1)
        .scaleEffect(rise ? 1.3 : 0.6)
        .allowsHitTesting(false)
        .onAppear {
            withAnimation(.easeOut(duration: 2.6)) { rise = true }
        }
    }
}
