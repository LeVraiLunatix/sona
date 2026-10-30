package fr.lunatix.alyra;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Outline;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import fr.lunatix.alyra.Models.Track;

/** Tokens de la D.A. « alyra. » (verre sombre, blanc pour l'actif, Inter Tight) + constructeurs de vues. */
final class UI {
    private UI() {}

    static final int BG = 0xFF0E1014;
    static final int TEXT = 0xFFF4F6F8;
    static final int TEXT2 = 0xB8F4F6F8;       // 72 %
    static final int TEXT3 = 0x80F4F6F8;       // 50 %
    static final int ACCENT = 0xFFF4F6F8;      // le blanc : aucune couleur de marque
    static final int ACCENT2 = 0xFFBFCBE0;
    static final int ON_ACCENT = 0xFF0E1014;
    static final int FILL = 0x12FFFFFF;
    static final int FILL_STRONG = 0x24FFFFFF;
    static final int FILL_FOCUS = 0x38FFFFFF;
    static final int HAIR = 0x1FFFFFFF;
    static final int GLASS = 0xE6181C26;
    static final int RAISED = 0xFF1E222B;      // fond de pochette en attente
    static final int ERR = 0xFFFF9B9B;

    static float density = 1f;
    static Typeface regular, semibold, bold;

    static void init(Context c) {
        density = c.getResources().getDisplayMetrics().density;
        regular = Typeface.createFromAsset(c.getAssets(), "fonts/InterTight-Regular.ttf");
        semibold = Typeface.createFromAsset(c.getAssets(), "fonts/InterTight-SemiBold.ttf");
        bold = Typeface.createFromAsset(c.getAssets(), "fonts/InterTight-Bold.ttf");
    }

    static int dp(float v) { return Math.round(v * density); }

    static String duration(int seconds) {
        if (seconds <= 0) return "";
        return (seconds / 60) + ":" + String.format("%02d", seconds % 60);
    }

    static String clock(int ms) {
        int s = Math.max(0, ms / 1000);
        return (s / 60) + ":" + String.format("%02d", s % 60);
    }

    // ---- texte ------------------------------------------------------------

    static TextView text(Context c, String s, float sp, int color, Typeface tf) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setTypeface(tf);
        t.setIncludeFontPadding(false);
        t.setLetterSpacing(-0.01f);
        return t;
    }

    /** Titres : gras, serres (comme .page-title du site). */
    static TextView heading(Context c, String s, float sp) {
        TextView t = text(c, s, sp, TEXT, bold);
        t.setLetterSpacing(-0.03f);
        return t;
    }

    static TextView oneLine(TextView t) {
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        return t;
    }

    // ---- focus ------------------------------------------------------------

    static GradientDrawable shape(int fill, int stroke, int strokePx, float radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(radiusDp));
        if (strokePx > 0) g.setStroke(strokePx, stroke);
        return g;
    }

    /** Focus : liseré blanc autour (cartes) ou pastille de verre (boutons, lignes). */
    static void focusable(View v, float radiusDp, boolean filled, float scale) {
        StateListDrawable sl = new StateListDrawable();
        if (filled) {
            sl.addState(new int[]{android.R.attr.state_focused}, shape(FILL_FOCUS, ACCENT, dp(2), radiusDp));
            sl.addState(new int[]{}, shape(Color.TRANSPARENT, 0, 0, radiusDp));
        } else {
            sl.addState(new int[]{android.R.attr.state_focused}, shape(Color.TRANSPARENT, ACCENT, dp(3), radiusDp + 3));
            sl.addState(new int[]{}, shape(Color.TRANSPARENT, 0, 0, radiusDp + 3));
        }
        v.setBackground(sl);
        v.setFocusable(true);
        v.setClickable(true);
        v.setOnFocusChangeListener((x, has) ->
                x.animate().scaleX(has ? scale : 1f).scaleY(has ? scale : 1f).setDuration(120).start());
    }

    static final class RoundOutline extends ViewOutlineProvider {
        private final float radius;
        RoundOutline(float radius) { this.radius = radius; }
        @Override public void getOutline(View view, Outline outline) {
            if (radius < 0) outline.setOval(0, 0, view.getWidth(), view.getHeight());
            else outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), radius);
        }
    }

    /** Image aux coins arrondis dessinee a la main (le decoupage par outline ne passe pas sur cette TV). */
    static final class RoundImage extends ImageView {
        private final float radiusPx; // < 0 = cercle
        private final android.graphics.Path clip = new android.graphics.Path();
        private final android.graphics.Paint ph = new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);
        private final android.graphics.RectF rect = new android.graphics.RectF();

        RoundImage(Context c, float radiusPx) {
            super(c);
            this.radiusPx = radiusPx;
            ph.setColor(RAISED);
        }

        @Override protected void onDraw(android.graphics.Canvas cv) {
            int w = getWidth(), h = getHeight();
            rect.set(0, 0, w, h);
            clip.reset();
            if (radiusPx < 0) clip.addOval(rect, android.graphics.Path.Direction.CW);
            else clip.addRoundRect(rect, radiusPx, radiusPx, android.graphics.Path.Direction.CW);
            cv.save();
            cv.clipPath(clip);
            cv.drawRect(rect, ph); // fond en attente de la pochette
            super.onDraw(cv);
            cv.restore();
        }
    }

    /** Image carree arrondie (radiusDp < 0 = cercle). */
    static ImageView cover(Context c, int sizeDp, float radiusDp) {
        ImageView iv = new RoundImage(c, radiusDp < 0 ? -1 : dp(radiusDp));
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
        iv.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return iv;
    }

    // ---- composants -------------------------------------------------------

    static View button(Context c, String label, boolean primary, Runnable onClick) {
        TextView t = text(c, label, 16, primary ? ON_ACCENT : TEXT, semibold);
        t.setSingleLine(true);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(24), dp(12), dp(24), dp(12));
        focusable(t, 24, true, 1.05f);
        StateListDrawable sl = new StateListDrawable();
        if (primary) {
            sl.addState(new int[]{android.R.attr.state_focused}, shape(0xFFFFFFFF, ACCENT2, dp(3), 24));
            sl.addState(new int[]{}, shape(0xE6F4F6F8, 0, 0, 24));
        } else {
            sl.addState(new int[]{android.R.attr.state_focused}, shape(FILL_FOCUS, ACCENT, dp(2), 24));
            sl.addState(new int[]{}, shape(FILL_STRONG, HAIR, dp(1), 24));
        }
        t.setBackground(sl);
        t.setOnClickListener(v -> onClick.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.rightMargin = dp(12);
        t.setLayoutParams(lp);
        return t;
    }

    /** Carte verticale : pochette + titre + sous-titre. */
    static View card(Context c, String title, String subtitle, String coverUrl, boolean round, int sizeDp, Runnable onClick) {
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(6), dp(6), dp(6), dp(6));
        focusable(box, round ? 0 : 18, false, 1.07f);
        ImageView iv = cover(c, sizeDp, round ? -1 : 18);
        Img.load(iv, coverUrl, dp(sizeDp));
        box.addView(iv);
        TextView t = oneLine(text(c, title == null ? "" : title, 15, TEXT, semibold));
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(dp(sizeDp), ViewGroup.LayoutParams.WRAP_CONTENT);
        tp.topMargin = dp(10);
        box.addView(t, tp);
        if (subtitle != null) {
            TextView s = oneLine(text(c, subtitle, 13, TEXT3, regular));
            box.addView(s, new LinearLayout.LayoutParams(dp(sizeDp), ViewGroup.LayoutParams.WRAP_CONTENT));
        }
        box.setOnClickListener(v -> onClick.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.rightMargin = dp(10);
        box.setLayoutParams(lp);
        return box;
    }

    /** Tuile d'acces rapide façon Spotify : petite pochette + titre dans une plaque de verre. */
    static View tile(Context c, String title, String subtitle, String coverUrl, Runnable onClick) {
        LinearLayout t = new LinearLayout(c);
        t.setGravity(Gravity.CENTER_VERTICAL);
        StateListDrawable sl = new StateListDrawable();
        sl.addState(new int[]{android.R.attr.state_focused}, shape(FILL_FOCUS, ACCENT, dp(2), 16));
        sl.addState(new int[]{}, shape(FILL, HAIR, dp(1), 16));
        t.setBackground(sl);
        t.setFocusable(true);
        t.setClickable(true);
        t.setOnFocusChangeListener((x, has) ->
                x.animate().scaleX(has ? 1.03f : 1f).scaleY(has ? 1.03f : 1f).setDuration(120).start());
        ImageView iv = cover(c, 64, 14);
        Img.load(iv, coverUrl, dp(64));
        t.addView(iv);
        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        TextView tx = oneLine(text(c, title == null ? "" : title, 16, TEXT, semibold));
        col.addView(tx);
        if (subtitle != null && !subtitle.isEmpty()) col.addView(oneLine(text(c, subtitle, 14, TEXT3, regular)));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        lp.leftMargin = dp(14);
        lp.rightMargin = dp(10);
        t.addView(col, lp);
        t.setOnClickListener(v -> onClick.run());
        return t;
    }

    /** Ligne de morceau (numero ou pochette, titre, artiste, duree) ; le morceau en cours est mis en avant. */
    static View trackRow(Context c, Track t, int number, boolean withCover, Runnable onClick) {
        LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(12), dp(7), dp(16), dp(7));
        focusable(row, 16, true, 1.0f);
        Track cur = Player.I.current();
        boolean now = cur != null && t.key().equals(cur.key());

        if (withCover) {
            ImageView iv = cover(c, 48, 12);
            Img.load(iv, t.coverUrl, dp(48));
            row.addView(iv);
        } else {
            TextView n = text(c, String.valueOf(number), 16, TEXT3, regular);
            n.setGravity(Gravity.CENTER);
            row.addView(n, new LinearLayout.LayoutParams(dp(40), ViewGroup.LayoutParams.WRAP_CONTENT));
        }

        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        TextView title = oneLine(text(c, t.title, 17, now ? ACCENT2 : TEXT, semibold));
        col.addView(title);
        String sub = t.artist == null ? "" : t.artist;
        if (withCover && t.album != null) sub += "  ·  " + t.album;
        TextView artist = oneLine(text(c, sub, 14, TEXT3, regular));
        col.addView(artist);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        cp.leftMargin = dp(14);
        row.addView(col, cp);

        TextView d = text(c, duration(t.duration), 14, TEXT3, regular);
        row.addView(d);

        row.setOnClickListener(v -> onClick.run());
        row.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return row;
    }

    static FrameLayout.LayoutParams fill() {
        return new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }
}
