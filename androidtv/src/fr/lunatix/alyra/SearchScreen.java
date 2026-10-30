package fr.lunatix.alyra;

import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

import org.json.JSONObject;

import fr.lunatix.alyra.Models.*;

final class SearchScreen extends Screen {
    private final EditText box;
    private final LinearLayout results;
    private int serial;
    private String queryId;
    private int total;
    private final ArrayList<Track> found = new ArrayList<>();
    private LinearLayout tracksHolder;
    private View moreButton;

    SearchScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        page.title("Rechercher");

        box = new EditText(a);
        box.setHint("Titre, artiste, album ou lien Spotify / Deezer / YouTube…");
        box.setHintTextColor(UI.MUTED);
        box.setTextColor(UI.TEXT);
        box.setTextSize(20);
        box.setTypeface(UI.regular);
        box.setSingleLine(true);
        box.setImeOptions(EditorInfo.IME_ACTION_SEARCH);
        box.setInputType(InputType.TYPE_CLASS_TEXT);
        box.setPadding(UI.dp(22), UI.dp(14), UI.dp(22), UI.dp(14));
        box.setBackground(UI.shape(UI.RAISED, 0, 0, 28));
        box.setOnFocusChangeListener((v, has) ->
                v.setBackground(has ? UI.shape(0xFF2F3A3E, UI.CYAN, UI.dp(2), 28) : UI.shape(UI.RAISED, 0, 0, 28)));
        a.keyboardOnClick(box);
        box.setOnEditorActionListener((v, action, ev) -> {
            if (action == EditorInfo.IME_ACTION_SEARCH || action == EditorInfo.IME_ACTION_DONE) {
                run(box.getText().toString());
                return true;
            }
            return false;
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(UI.dp(560), ViewGroup.LayoutParams.WRAP_CONTENT);
        page.col.addView(box, lp);

        results = new LinearLayout(a);
        results.setOrientation(LinearLayout.VERTICAL);
        results.setClipChildren(false);
        page.col.addView(results, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        hint("Tape ta recherche (OK sur le champ ouvre le clavier ou la dictée), puis valide.");
    }

    private void hint(String s) {
        results.removeAllViews();
        TextView t = UI.text(a, s, 16, UI.MUTED, UI.italic);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(14);
        results.addView(t, lp);
    }

    void run(String text) {
        final String q = text == null ? "" : text.trim();
        if (q.isEmpty()) return;
        if (!Api.configured()) { a.toast("Configure d'abord le serveur dans Réglages"); return; }
        box.setText(q);
        a.hideKeyboard(box);
        final int my = ++serial;
        found.clear();
        queryId = null;
        total = 0;
        results.removeAllViews();

        if (q.startsWith("http")) { resolveLink(q, my); return; }

        // trois sections remplies independamment, dans un ordre d'affichage fixe
        LinearLayout artistsBox = section("Artistes");
        LinearLayout albumsBox = section("Albums");
        TextView th = sectionTitle("Titres");
        tracksHolder = new LinearLayout(a);
        tracksHolder.setOrientation(LinearLayout.VERTICAL);
        results.addView(tracksHolder, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        th.setVisibility(View.GONE);

        Api.async(() -> Api.searchArtists(q), list -> {
            if (my != serial) return;
            for (Artist ar : list) artistsBox.addView(artistCard(ar));
            show(artistsBox, !list.isEmpty());
        }, m -> {});
        Api.async(() -> Api.searchAlbums(q), list -> {
            if (my != serial) return;
            for (Album al : list) albumsBox.addView(albumCard(al));
            show(albumsBox, !list.isEmpty());
        }, m -> {});
        Api.async(() -> Api.search(q, null, 0), r -> {
            if (my != serial) return;
            queryId = r.queryId;
            total = r.total;
            if (r.tracks.isEmpty()) {
                if (artistsBox.getChildCount() == 0 && albumsBox.getChildCount() == 0)
                    hint("Aucun résultat pour « " + q + " ».");
                return;
            }
            th.setVisibility(View.VISIBLE);
            addTracks(r.tracks);
            a.ensureFocus();
        }, m -> {
            if (my != serial) return;
            TextView e = UI.text(a, m, 17, UI.MAGENTA, UI.regular);
            results.addView(e);
        });
    }

    private TextView sectionTitle(String s) {
        TextView t = UI.text(a, s, 22, UI.TEXT, UI.semibold);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(22);
        lp.bottomMargin = UI.dp(8);
        results.addView(t, lp);
        return t;
    }

    /** Titre + rangee horizontale masques jusqu'a l'arrivee des donnees ; renvoie la rangee. */
    private LinearLayout section(String title) {
        TextView t = sectionTitle(title);
        android.widget.HorizontalScrollView hs = new android.widget.HorizontalScrollView(a);
        hs.setHorizontalScrollBarEnabled(false);
        hs.setClipChildren(false);
        LinearLayout inner = new LinearLayout(a);
        inner.setClipChildren(false);
        inner.setPadding(UI.dp(4), UI.dp(4), UI.dp(4), UI.dp(10));
        hs.addView(inner);
        results.addView(hs);
        t.setVisibility(View.GONE);
        hs.setVisibility(View.GONE);
        inner.setTag(new View[]{t, hs});
        return inner;
    }

    private void show(LinearLayout inner, boolean visible) {
        View[] v = (View[]) inner.getTag();
        v[0].setVisibility(visible ? View.VISIBLE : View.GONE);
        v[1].setVisibility(visible ? View.VISIBLE : View.GONE);
        if (visible) a.ensureFocus();
    }

    private void addTracks(List<Track> tracks) {
        int base = found.size();
        found.addAll(tracks);
        if (moreButton != null) tracksHolder.removeView(moreButton);
        for (int i = 0; i < tracks.size(); i++) {
            final int idx = base + i;
            tracksHolder.addView(UI.trackRow(a, tracks.get(i), idx + 1, true,
                    () -> Player.I.play(new ArrayList<>(found), idx)));
        }
        if (found.size() < total) {
            LinearLayout wrap = new LinearLayout(a);
            wrap.setPadding(0, UI.dp(10), 0, 0);
            wrap.addView(UI.button(a, "Voir plus de titres", false, this::more));
            moreButton = wrap;
            tracksHolder.addView(wrap);
        } else {
            moreButton = null;
        }
    }

    private void more() {
        final int my = serial;
        final String qid = queryId;
        final int off = found.size();
        Api.async(() -> Api.search(null, qid, off), r -> {
            if (my != serial) return;
            total = r.total;
            addTracks(r.tracks);
        }, a::toast);
    }

    private void resolveLink(String q, int my) {
        TextView t = UI.text(a, "Résolution du lien…", 16, UI.MUTED, UI.italic);
        results.addView(t);
        Api.async(() -> Api.resolve(q), o -> {
            if (my != serial) return;
            results.removeAllViews();
            try {
                String kind = o.optString("kind");
                if ("track".equals(kind)) {
                    Track tr = Track.from(o.getJSONObject("track"));
                    ArrayList<Track> one = new ArrayList<>();
                    one.add(tr);
                    Player.I.play(one, 0);
                    hint("Lecture de « " + tr.title + " ».");
                } else if ("album".equals(kind) || "playlist".equals(kind)) {
                    Album al = Album.from(o.getJSONObject("album"));
                    a.push(new AlbumScreen(a, al.source, al.sourceId, "playlist".equals(kind)));
                    hint("Lien ouvert.");
                } else if ("artist".equals(kind)) {
                    Artist ar = Artist.from(o.getJSONObject("artist"));
                    a.push(new ArtistScreen(a, ar.source, ar.sourceId));
                    hint("Lien ouvert.");
                }
            } catch (Exception e) {
                hint("Lien non reconnu.");
            }
        }, m -> {
            if (my != serial) return;
            hint(m);
        });
    }

    @Override View view() { return page.root(); }

}
