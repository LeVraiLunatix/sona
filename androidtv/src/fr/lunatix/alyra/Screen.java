package fr.lunatix.alyra;

import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.List;
import java.util.concurrent.Callable;

import fr.lunatix.alyra.Models.*;

/** Un ecran du contenu (le rail de gauche et le mini-lecteur sont a part). */
abstract class Screen {
    final MainActivity a;
    Page page;

    Screen(MainActivity a) { this.a = a; }

    abstract View view();

    /** Appele quand l'ecran redevient visible. */
    void onShow() {}

    interface Maker<T> { View make(T item); }

    /**
     * Ajoute tout de suite un titre + une rangee vides, les remplit au retour du
     * serveur (ordre d'affichage preserve), et les masque si rien n'arrive.
     */
    <T> void asyncRow(String title, Callable<List<T>> work, Maker<T> maker) {
        TextView t = UI.heading(a, title, 24);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(22);
        lp.bottomMargin = UI.dp(8);
        page.col.addView(t, lp);
        LinearLayout row = page.row();
        t.setVisibility(View.GONE);
        row.setVisibility(View.GONE);
        ((View) row.getParent()).setVisibility(View.GONE);
        Api.async(work, items -> {
            if (items == null || items.isEmpty()) return;
            for (T it : items) row.addView(maker.make(it));
            t.setVisibility(View.VISIBLE);
            row.setVisibility(View.VISIBLE);
            ((View) row.getParent()).setVisibility(View.VISIBLE);
            a.ensureFocus();
        }, msg -> {});
    }

    View entryCard(List<Entry> list, int idx) {
        Entry e = list.get(idx);
        boolean artist = "artist".equals(e.kind);
        String sub = "album".equals(e.kind) || artist ? (artist ? null : e.subtitle) : e.subtitle;
        return UI.card(a, e.title, sub, e.coverUrl, artist, artist ? 130 : 150, () -> openEntry(list, idx));
    }

    void openEntry(List<Entry> list, int idx) {
        Entry e = list.get(idx);
        if ("album".equals(e.kind)) a.push(new AlbumScreen(a, e.source, e.sourceId, false));
        else if ("artist".equals(e.kind)) a.push(new ArtistScreen(a, e.source, e.sourceId));
        else {
            java.util.ArrayList<Track> q = new java.util.ArrayList<>();
            int start = 0;
            for (int i = 0; i < list.size(); i++) {
                if (!"track".equals(list.get(i).kind)) continue;
                if (i == idx) start = q.size();
                q.add(list.get(i).toTrack());
            }
            Player.I.play(q, start);
        }
    }

    View albumCard(Album al) {
        return UI.card(a, al.title, al.artist, al.coverUrl, false, 160,
                () -> a.push(new AlbumScreen(a, al.source, al.sourceId, false)));
    }

    View artistCard(Artist ar) {
        return UI.card(a, ar.name, "Artiste", ar.pictureUrl, true, 140,
                () -> a.push(new ArtistScreen(a, ar.source, ar.sourceId)));
    }
}
