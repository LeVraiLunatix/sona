package fr.lunatix.alyra;

import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;

import java.util.ArrayList;
import java.util.List;

import fr.lunatix.alyra.Models.*;

final class ArtistScreen extends Screen {
    private final String source, id;
    private final LinearLayout header;
    private final List<Track> top = new ArrayList<>();

    ArtistScreen(MainActivity a, String source, String id) {
        super(a);
        this.source = source;
        this.id = id;
        page = new Page(a);
        header = new LinearLayout(a);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        page.add(header);
        Api.async(() -> Api.artist(source, id), this::fillHeader, m -> page.error(m));

        // titres populaires : liste, en tete ; le reste en rangees
        page.section("Titres populaires");
        final int slot = page.count();
        Api.async(() -> Api.topTracks(source, id), tracks -> {
            top.addAll(tracks);
            // insere apres le titre de section, avant les rangees deja ajoutees
            int pos = slot;
            for (int i = 0; i < Math.min(tracks.size(), 8); i++) {
                final int idx = i;
                View row = UI.trackRow(a, tracks.get(i), i + 1, true, () -> Player.I.play(new ArrayList<>(top), idx));
                page.col.addView(row, pos++);
            }
            a.ensureFocus();
        }, m -> {});

        asyncRow("Albums", () -> Api.artistAlbums(source, id).get(0), this::albumCard);
        asyncRow("Singles et EP", () -> Api.artistAlbums(source, id).get(1), this::albumCard);
        asyncRow("Artistes similaires", () -> Api.relatedArtists(source, id), this::artistCard);
    }

    private void fillHeader(Artist ar) {
        ImageView iv = UI.cover(a, 170, -1);
        Img.load(iv, ar.pictureUrl, UI.dp(170));
        header.addView(iv);
        LinearLayout info = new LinearLayout(a);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(UI.dp(28), 0, 0, 0);
        info.addView(UI.text(a, ar.name, 38, UI.TEXT, UI.semibold));
        LinearLayout actions = new LinearLayout(a);
        actions.setGravity(Gravity.CENTER_VERTICAL);
        actions.setPadding(0, UI.dp(16), 0, 0);
        actions.addView(UI.button(a, "Écouter", true, () -> {
            if (!top.isEmpty()) Player.I.play(new ArrayList<>(top), 0);
        }));
        actions.addView(UI.button(a, "Radio de l'artiste", false, () -> {
            a.toast("Radio de " + ar.name + "…");
            Api.async(() -> Api.artistRadio(source, id), tracks ->
                    Player.I.playQueue(tracks, 0, () -> Api.artistRadio(source, id)), a::toast);
        }));
        actions.addView(UI.button(a, "+ Bibliothèque", false, () ->
                Api.async(() -> {
                    Api.send("POST", "/library/artist", new org.json.JSONObject()
                            .put("source", source).put("source_id", id));
                    return true;
                }, ok -> a.toast("Artiste ajouté"), a::toast)));
        info.addView(actions);
        header.addView(info, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        a.ensureFocus();
    }

    @Override View view() { return page.root(); }
}
