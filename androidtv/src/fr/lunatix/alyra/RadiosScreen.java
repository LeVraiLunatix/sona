package fr.lunatix.alyra;

import android.content.Context;
import android.view.View;
import android.widget.LinearLayout;

import java.util.List;

import fr.lunatix.alyra.Models.*;

final class RadiosScreen extends Screen {
    RadiosScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        page.title("Radios");
        if (!Api.configured()) {
            page.note("Aucun serveur configuré.");
            return;
        }
        page.loading();
        final int keep = page.count() - 1;
        Api.async(Api::radios, groups -> {
            page.truncate(keep);
            for (RadioGroup g : groups) {
                page.section(g.title);
                LinearLayout row = page.row();
                for (Radio r : g.radios) row.addView(radioCard(a, r));
            }
            a.ensureFocus();
        }, msg -> {
            page.truncate(keep);
            page.error(msg);
        });
    }

    static View radioCard(MainActivity a, Radio r) {
        return UI.card(a, r.title, "Radio", r.pictureUrl, false, 150, () -> startRadio(a, r));
    }

    static void startRadio(MainActivity a, Radio r) {
        a.toast("Radio " + r.title + "…");
        Api.async(() -> Api.radioTracks(r.id), tracks ->
                Player.I.playQueue(tracks, 0, () -> Api.radioTracks(r.id)), a::toast);
    }

    @Override View view() { return page.root(); }
}
