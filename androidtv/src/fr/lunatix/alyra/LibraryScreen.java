package fr.lunatix.alyra;

import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;

import java.util.ArrayList;
import java.util.List;

import fr.lunatix.alyra.Models.*;

final class LibraryScreen extends Screen {
    private final int fixed;
    private String kind = "track";

    LibraryScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        page.title("Bibliothèque");
        if (!Api.configured()) {
            page.note("Aucun serveur configuré.");
            fixed = page.count();
            return;
        }
        LinearLayout tabs = page.actions();
        tabs.addView(UI.button(a, "Titres", true, () -> show("track")));
        tabs.addView(UI.button(a, "Albums", false, () -> show("album")));
        tabs.addView(UI.button(a, "Artistes", false, () -> show("artist")));
        fixed = page.count();
        show("track");
    }

    private void show(String k) {
        kind = k;
        page.truncate(fixed);
        page.loading();
        Api.async(() -> {
            List<Entry> all = new ArrayList<>();
            for (int off = 0; off < 300; off += 100) {
                List<Entry> part = Api.library(k, off, 100);
                all.addAll(part);
                if (part.size() < 100) break;
            }
            return all;
        }, items -> {
            if (!k.equals(kind)) return;
            page.truncate(fixed);
            if (items.isEmpty()) {
                page.note("Rien ici pour l'instant — ajoute des éléments depuis la recherche.");
                return;
            }
            if ("track".equals(k)) {
                for (int i = 0; i < items.size(); i++) {
                    final int idx = i;
                    page.add(UI.trackRow(a, items.get(i).toTrack(), i + 1, true, () -> openEntry(items, idx)));
                }
            } else {
                int perRow = Math.max(3, (a.contentWidthDp() - 80) / ("artist".equals(k) ? 145 : 165));
                LinearLayout row = null;
                for (int i = 0; i < items.size(); i++) {
                    if (i % perRow == 0) row = page.row();
                    row.addView(entryCard(items, i));
                }
            }
            a.ensureFocus();
        }, page::error);
    }

    @Override View view() { return page.root(); }
}
