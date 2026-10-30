package fr.lunatix.alyra;

import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;

import fr.lunatix.alyra.Models.*;

final class AlbumScreen extends Screen {
    private final LinearLayout header;
    private final int fixed;

    AlbumScreen(MainActivity a, String source, String id, boolean playlist) {
        super(a);
        page = new Page(a);
        header = new LinearLayout(a);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        page.add(header);
        fixed = page.count();
        page.loading();
        Api.async(() -> playlist ? Api.playlist(source, id) : Api.album(source, id), this::fill, m -> {
            page.truncate(fixed);
            page.error(m);
        });
    }

    private void fill(Album al) {
        page.truncate(fixed);
        ImageView iv = UI.cover(a, 230, 12);
        Img.load(iv, al.coverUrl, UI.dp(230));
        header.addView(iv);

        LinearLayout info = new LinearLayout(a);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(UI.dp(28), 0, 0, 0);
        TextView t = UI.heading(a, al.title, 38);
        t.setMaxLines(2);
        info.addView(t);
        String meta = (al.artist == null ? "" : al.artist)
                + (al.year != null ? "  ·  " + al.year : "")
                + (al.tracks.size() > 0 ? "  ·  " + al.tracks.size() + " titres" : "");
        info.addView(UI.text(a, meta, 17, UI.TEXT2, UI.regular));

        LinearLayout actions = new LinearLayout(a);
        actions.setGravity(Gravity.CENTER_VERTICAL);
        actions.setPadding(0, UI.dp(18), 0, 0);
        actions.addView(UI.button(a, "Tout écouter", true, () -> {
            if (!al.tracks.isEmpty()) Player.I.play(new ArrayList<>(al.tracks), 0);
        }));
        actions.addView(UI.button(a, "Aléatoire", false, () -> {
            if (al.tracks.isEmpty()) return;
            ArrayList<Track> q = new ArrayList<>(al.tracks);
            java.util.Collections.shuffle(q);
            Player.I.play(q, 0);
        }));
        info.addView(actions);
        // deuxieme rangee : la premiere n'a pas la place pour quatre boutons a cote de la pochette
        actions = new LinearLayout(a);
        actions.setGravity(Gravity.CENTER_VERTICAL);
        actions.setPadding(0, UI.dp(8), 0, 0);
        if (al.artistId != null) {
            actions.addView(UI.button(a, "Voir l'artiste", false,
                    () -> a.push(new ArtistScreen(a, al.source, al.artistId))));
        }
        actions.addView(UI.button(a, "Ajouter à la bibliothèque", false, () ->
                Api.async(() -> {
                    Api.send("POST", "/library/album", new org.json.JSONObject()
                            .put("source", al.source).put("source_id", al.sourceId));
                    return true;
                }, ok -> a.toast("Album ajouté à la bibliothèque"), a::toast)));
        info.addView(actions);
        header.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(1, UI.dp(18));
        page.col.addView(new View(a), sp);
        page.tracks(al.tracks, true, false);
        a.ensureFocus();
    }

    @Override View view() { return page.root(); }
}
