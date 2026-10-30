package fr.lunatix.alyra;

import android.content.Context;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.List;

import fr.lunatix.alyra.Models.Track;

/** Page defilante verticale faite de sections ; les ecrans y empilent titres, rangees de cartes et listes. */
final class Page {
    final Context ctx;
    final ScrollView scroll;
    final LinearLayout col;

    Page(Context c) {
        ctx = c;
        scroll = new ScrollView(c);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setClipChildren(false);
        scroll.setClipToPadding(false);
        scroll.setFillViewport(true);
        col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setClipChildren(false);
        col.setPadding(UI.dp(40), UI.dp(34), UI.dp(40), UI.dp(110)); // place pour le mini-lecteur
        scroll.addView(col, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    View root() { return scroll; }

    Page add(View v) { col.addView(v); return this; }

    Page title(String s) {
        TextView t = UI.text(ctx, s, 34, UI.TEXT, UI.semibold);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = UI.dp(18);
        col.addView(t, lp);
        return this;
    }

    Page section(String s) {
        TextView t = UI.text(ctx, s, 22, UI.TEXT, UI.semibold);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(22);
        lp.bottomMargin = UI.dp(8);
        col.addView(t, lp);
        return this;
    }

    Page note(String s) {
        TextView t = UI.text(ctx, s, 16, UI.MUTED, UI.italic);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(10);
        col.addView(t, lp);
        return this;
    }

    /** Rangee horizontale ; renvoie le conteneur pour y ajouter les cartes. */
    LinearLayout row() {
        HorizontalScrollView hs = new HorizontalScrollView(ctx);
        hs.setHorizontalScrollBarEnabled(false);
        hs.setClipChildren(false);
        hs.setClipToPadding(false);
        LinearLayout inner = new LinearLayout(ctx);
        inner.setOrientation(LinearLayout.HORIZONTAL);
        inner.setClipChildren(false);
        inner.setPadding(UI.dp(4), UI.dp(4), UI.dp(4), UI.dp(10));
        hs.addView(inner);
        col.addView(hs, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return inner;
    }

    LinearLayout actions() {
        LinearLayout l = new LinearLayout(ctx);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(14);
        lp.bottomMargin = UI.dp(6);
        col.addView(l, lp);
        return l;
    }

    /** Liste verticale de morceaux ; un clic lance la file "tracks" a partir de ce morceau. */
    void tracks(List<Track> tracks, boolean numbered, boolean withCover) {
        for (int i = 0; i < tracks.size(); i++) {
            final int idx = i;
            col.addView(UI.trackRow(ctx, tracks.get(i), i + 1, withCover && !numbered,
                    () -> Player.I.play(tracks, idx)));
        }
    }

    void loading() { note("Chargement…"); }

    void error(String msg) {
        TextView t = UI.text(ctx, msg, 17, UI.MAGENTA, UI.regular);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(12);
        col.addView(t, lp);
    }

    /** Retire tout ce qui suit le premier `keep` enfants (reaffichage apres chargement). */
    void truncate(int keep) {
        while (col.getChildCount() > keep) col.removeViewAt(col.getChildCount() - 1);
    }

    int count() { return col.getChildCount(); }
}
