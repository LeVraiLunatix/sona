package fr.lunatix.alyra;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import fr.lunatix.alyra.Models.Track;

/** Lecteur plein ecran : pochette, titre, barre de progression, transport, coeur. */
final class NowPlaying implements Player.Listener {
    final FrameLayout root;
    private final MainActivity a;
    private final ImageView cover;
    private final TextView title, artist, album, status, upNext, elapsed, remaining;
    private final Progress bar;
    private final IconView prev, play, next, heart;
    private String shownKey;

    /** Barre de progression focalisable : gauche/droite = -/+ 10 s. */
    static final class Progress extends View {
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF r = new RectF();

        Progress(Context c) {
            super(c);
            setFocusable(true);
            setClickable(true);
        }

        @Override protected void onDraw(Canvas c) {
            int w = getWidth(), h = getHeight();
            float th = UI.dp(isFocused() ? 8 : 5);
            float y = h / 2f;
            r.set(0, y - th / 2, w, y + th / 2);
            p.setColor(UI.RAISED);
            c.drawRoundRect(r, th / 2, th / 2, p);
            int dur = Player.I.duration();
            float f = dur > 0 ? Math.min(1f, Player.I.position() / (float) dur) : 0f;
            r.set(0, y - th / 2, w * f, y + th / 2);
            p.setColor(UI.CYAN);
            c.drawRoundRect(r, th / 2, th / 2, p);
            if (isFocused()) {
                p.setColor(UI.TEXT);
                c.drawCircle(w * f, y, UI.dp(8), p);
            }
        }

        @Override public boolean onKeyDown(int code, KeyEvent e) {
            if (code == KeyEvent.KEYCODE_DPAD_LEFT) { Player.I.seekBy(-10000); return true; }
            if (code == KeyEvent.KEYCODE_DPAD_RIGHT) { Player.I.seekBy(10000); return true; }
            return super.onKeyDown(code, e);
        }
    }

    NowPlaying(MainActivity a) {
        this.a = a;
        root = new FrameLayout(a);
        root.setBackgroundColor(UI.BG);
        root.setVisibility(View.GONE);
        root.setClickable(true);

        LinearLayout h = new LinearLayout(a);
        h.setOrientation(LinearLayout.HORIZONTAL);
        h.setGravity(Gravity.CENTER_VERTICAL);
        h.setPadding(UI.dp(70), UI.dp(30), UI.dp(70), UI.dp(30));
        root.addView(h, UI.fill());

        cover = UI.cover(a, 300, 16);
        h.addView(cover);

        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(UI.dp(50), 0, 0, 0);
        h.addView(col, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        title = UI.text(a, "", 36, UI.TEXT, UI.semibold);
        title.setMaxLines(2);
        col.addView(title);
        artist = UI.oneLine(UI.text(a, "", 22, UI.CYAN, UI.italic));
        LinearLayout.LayoutParams ap = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        ap.topMargin = UI.dp(8);
        col.addView(artist, ap);
        album = UI.oneLine(UI.text(a, "", 16, UI.MUTED, UI.regular));
        col.addView(album);

        bar = new Progress(a);
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, UI.dp(28));
        bp.topMargin = UI.dp(30);
        col.addView(bar, bp);

        LinearLayout times = new LinearLayout(a);
        elapsed = UI.text(a, "0:00", 14, UI.MUTED, UI.regular);
        remaining = UI.text(a, "", 14, UI.MUTED, UI.regular);
        remaining.setGravity(Gravity.END);
        times.addView(elapsed, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        times.addView(remaining, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        col.addView(times);

        LinearLayout controls = new LinearLayout(a);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        controls.setPadding(0, UI.dp(16), 0, UI.dp(10)); // marge pour l'anneau de focus agrandi
        prev = icon(controls, IconView.PREV, 56, false);
        play = icon(controls, IconView.PLAY, 72, true);
        next = icon(controls, IconView.NEXT, 56, false);
        heart = icon(controls, IconView.HEART, 56, false);
        col.addView(controls);
        prev.setOnClickListener(v -> Player.I.previous());
        play.setOnClickListener(v -> Player.I.toggle());
        next.setOnClickListener(v -> Player.I.next());
        heart.setOnClickListener(v -> toggleLike());

        status = UI.text(a, "", 16, UI.MAGENTA, UI.regular);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        sp.topMargin = UI.dp(16);
        col.addView(status, sp);
        upNext = UI.oneLine(UI.text(a, "", 15, UI.MUTED, UI.italic));
        LinearLayout.LayoutParams up = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        up.topMargin = UI.dp(8);
        col.addView(upNext, up);
    }

    private IconView icon(LinearLayout parent, int type, int sizeDp, boolean accent) {
        IconView v = new IconView(a, type, sizeDp, accent);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(UI.dp(sizeDp), UI.dp(sizeDp));
        lp.rightMargin = UI.dp(16);
        parent.addView(v, lp);
        return v;
    }

    boolean isOpen() { return root.getVisibility() == View.VISIBLE; }

    void open() {
        root.setVisibility(View.VISIBLE);
        shownKey = null;
        Player.I.addListener(this);
        onChange();
        play.requestFocus();
    }

    void close() {
        root.setVisibility(View.GONE);
        Player.I.removeListener(this);
    }

    private void toggleLike() {
        Track t = Player.I.current();
        if (t == null) return;
        boolean now = !Api.isLiked(t.key());
        heart.setType(now ? IconView.HEART_ON : IconView.HEART);
        Api.async(() -> { Api.setLiked(t, now); return true; }, ok -> {}, m -> {
            a.toast(m);
            onChange();
        });
    }

    @Override public void onChange() {
        Track t = Player.I.current();
        if (t == null) { a.closeNowPlaying(); return; }
        if (!t.key().equals(shownKey)) {
            shownKey = t.key();
            title.setText(t.title);
            artist.setText(t.artist == null ? "" : t.artist);
            album.setText(t.album == null ? "" : t.album);
            Img.load(cover, t.coverUrl, UI.dp(300));
        }
        int st = Player.I.state();
        play.setType(st == Player.PLAYING ? IconView.PAUSE : st == Player.LOADING ? IconView.LOADING : IconView.PLAY);
        heart.setType(Api.isLiked(t.key()) ? IconView.HEART_ON : IconView.HEART);
        prev.setAlpha(Player.I.hasPrevious() ? 1f : .4f);
        next.setAlpha(Player.I.hasNext() ? 1f : .4f);
        if (st == Player.LOADING) status.setText("Préparation du morceau… (le serveur le récupère, quelques secondes)");
        else if (st == Player.ERROR) status.setText(Player.I.error());
        else status.setText("");
        elapsed.setText(UI.clock(Player.I.position()));
        int dur = Player.I.duration();
        remaining.setText(dur > 0 ? UI.clock(dur) : "");
        bar.invalidate();
        int ni = Player.I.index() + 1;
        upNext.setText(ni < Player.I.queue().size() ? "À suivre : " + Player.I.queue().get(ni).title : "");
    }
}
