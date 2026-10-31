package fr.lunatix.alyra;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;

import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;

import fr.lunatix.alyra.Models.*;

/** Accueil façon Spotify : salutation, tuiles d'acces rapide (2 colonnes), puis etageres horizontales. */
final class HomeScreen extends Screen {
    HomeScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        int hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY);
        page.title(hour < 5 || hour >= 18 ? "Bonsoir" : hour < 12 ? "Bonjour" : "Bon après-midi");
        if (!Api.configured()) {
            page.note("Tu n'es pas connecté à ton compte alyra.");
            page.actions().addView(UI.button(a, "Se connecter avec un QR code", true, () -> a.push(new LoginScreen(a))));
            return;
        }

        // acces rapide : les derniers titres ecoutes, completes par la bibliotheque
        final LinearLayout grid = new LinearLayout(a);
        grid.setOrientation(LinearLayout.VERTICAL);
        grid.setClipChildren(false);
        page.add(grid);
        Api.async(() -> {
            List<Entry> out = new ArrayList<>(Api.history(8));
            if (out.size() < 8) out.addAll(Api.library("track", 0, 8 - out.size()));
            return out;
        }, items -> fillGrid(grid, items), m -> {});

        // Sona Connect : la lecture en cours sur un autre appareil du compte, a reprendre ici
        asyncRow("Sur tes autres appareils", Connect.I::sessionElsewhere, s -> {
            org.json.JSONObject tr = s.optJSONObject("track");
            return UI.card(a, tr.optString("title"), "Sur " + s.optString("device_name"),
                    tr.isNull("cover_url") ? null : tr.optString("cover_url"), false, 160,
                    () -> { a.toast("Reprise ici…"); Connect.I.transferHere(); });
        });
        asyncRow("Reprendre l'écoute", () -> Api.history(20), maker());
        asyncRow("Ta bibliothèque", () -> Api.library("track", 0, 20), maker());
        asyncRow("Tes albums", () -> Api.library("album", 0, 20), maker());
        asyncRow("Tes artistes", () -> Api.library("artist", 0, 20), maker());
        asyncRow("Radios", () -> {
            List<RadioGroup> gs = Api.radios();
            ArrayList<Radio> out = new ArrayList<>();
            for (RadioGroup g : gs) out.addAll(g.radios);
            return new ArrayList<>(out.subList(0, Math.min(out.size(), 14)));
        }, r -> RadiosScreen.radioCard(a, r));
    }

    private void fillGrid(LinearLayout grid, List<Entry> items) {
        if (items.isEmpty()) return;
        for (int i = 0; i < items.size(); i += 2) {
            LinearLayout row = new LinearLayout(a);
            row.setClipChildren(false);
            for (int j = i; j < Math.min(i + 2, items.size()); j++) {
                final int idx = j;
                Entry e = items.get(j);
                View tile = UI.tile(a, e.title, "artist".equals(e.kind) ? "Artiste" : e.subtitle, e.coverUrl, () -> openEntry(items, idx));
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
                lp.rightMargin = UI.dp(12);
                lp.bottomMargin = UI.dp(12);
                row.addView(tile, lp);
            }
            grid.addView(row, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        }
        a.ensureFocus();
    }

    /** Fabrique de cartes pour une rangee d'entrees : la liste vue jusqu'ici sert de file de lecture. */
    private Maker<Entry> maker() {
        final ArrayList<Entry> seen = new ArrayList<>();
        return e -> {
            seen.add(e);
            final int idx = seen.size() - 1;
            boolean artist = "artist".equals(e.kind);
            return UI.card(a, e.title, artist ? "Artiste" : e.subtitle, e.coverUrl, artist, artist ? 140 : 160,
                    () -> openEntry(seen, idx));
        };
    }

    @Override View view() { return page.root(); }
}
