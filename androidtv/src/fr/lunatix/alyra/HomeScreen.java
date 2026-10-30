package fr.lunatix.alyra;

import java.util.ArrayList;
import java.util.List;

import android.view.View;

import fr.lunatix.alyra.Models.*;

final class HomeScreen extends Screen {
    HomeScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        page.title("Écouter");
        if (!Api.configured()) {
            page.note("Aucun serveur configuré — ouvre Réglages pour renseigner l'adresse et le jeton.");
            return;
        }
        asyncRow("Reprendre l'écoute", () -> Api.history(20), maker());
        asyncRow("Ma bibliothèque", () -> Api.library("track", 0, 20), maker());
        asyncRow("Albums", () -> Api.library("album", 0, 20), maker());
        asyncRow("Artistes", () -> Api.library("artist", 0, 20), maker());
        asyncRow("Radios", () -> {
            List<RadioGroup> gs = Api.radios();
            ArrayList<Radio> out = new ArrayList<>();
            for (RadioGroup g : gs) out.addAll(g.radios);
            return new ArrayList<>(out.subList(0, Math.min(out.size(), 14)));
        }, r -> RadiosScreen.radioCard(a, r));
    }

    /** Fabrique de cartes pour une rangee d'entrees : la liste vue jusqu'ici sert de file de lecture. */
    private Maker<Entry> maker() {
        final ArrayList<Entry> seen = new ArrayList<>();
        return e -> {
            seen.add(e);
            final int idx = seen.size() - 1;
            boolean artist = "artist".equals(e.kind);
            return UI.card(a, e.title, artist ? null : e.subtitle, e.coverUrl, artist, artist ? 130 : 150,
                    () -> openEntry(seen, idx));
        };
    }

    @Override View view() { return page.root(); }
}
