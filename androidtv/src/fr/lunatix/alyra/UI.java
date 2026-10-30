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

/** Tokens du design "Encre" (sombre) + petits constructeurs de vues. */
final class UI {
    private UI() {}

    static final int BG = 0xFF121112;
    static final int SURFACE = 0xFF1C1B1C;
    static final int RAISED = 0xFF2C2B2D;
    static final int TEXT = 0xFFF4F1EF;
    static final int MUTED = 0xFF8F8C8F;
    static final int SOFT = 0xFFAFACAE;
    static final int CYAN = 0xFF28B8E0;
    static final int MAGENTA = 0xFFFF4FA0;

    static float density = 1f;
    static Typeface regular, semibold, italic;

    static void init(Context c) {
        density = c.getResources().getDisplayMetrics().density;
        regular = Typeface.createFromAsset(c.getAssets(), "fonts/SourceSerif4-Regular.ttf");
        semibold = Typeface.createFromAsset(c.getAssets(), "fonts/SourceSerif4-SemiBold.ttf");
        italic = Typeface.createFromAsset(c.getAssets(), "fonts/SourceSerif4-Italic.ttf");
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

    /** Fond de focus : liseré cyan autour (cartes) ou pastille pleine (boutons, lignes). */
    static void focusable(View v, float radiusDp, boolean filled, float scale) {
        StateListDrawable sl = new StateListDrawable();
        if (filled) {
            sl.addState(new int[]{android.R.attr.state_focused}, shape(0xFF2F3A3E, CYAN, dp(2), radiusDp));
            sl.addState(new int[]{}, shape(Color.TRANSPARENT, 0, 0, radiusDp));
        } else {
            sl.addState(new int[]{android.R.attr.state_focused}, shape(Color.TRANSPARENT, CYAN, dp(3), radiusDp + 3));
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

    /** Image carree arrondie (radiusDp < 0 = cercle). */
    static ImageView cover(Context c, int sizeDp, float radiusDp) {
        ImageView iv = new ImageView(c);
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
        iv.setBackgroundColor(RAISED);
        iv.setOutlineProvider(new RoundOutline(radiusDp < 0 ? -1 : dp(radiusDp)));
        iv.setClipToOutline(true);
        iv.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return iv;
    }

    // ---- composants -------------------------------------------------------

    static View button(Context c, String label, boolean primary, Runnable onClick) {
        TextView t = text(c, label, 16, primary ? BG : TEXT, semibold);
        t.setSingleLine(true);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(22), dp(11), dp(22), dp(11));
        focusable(t, 22, true, 1.05f);
        if (primary) {
            StateListDrawable sl = new StateListDrawable();
            sl.addState(new int[]{android.R.attr.state_focused}, shape(0xFF7FD9F2, TEXT, dp(2), 22));
            sl.addState(new int[]{}, shape(CYAN, 0, 0, 22));
            t.setBackground(sl);
        } else {
            StateListDrawable sl = new StateListDrawable();
            sl.addState(new int[]{android.R.attr.state_focused}, shape(0xFF2F3A3E, CYAN, dp(2), 22));
            sl.addState(new int[]{}, shape(RAISED, 0, 0, 22));
            t.setBackground(sl);
        }
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
        box.setPadding(dp(5), dp(5), dp(5), dp(5));
        focusable(box, round ? 0 : 10, false, 1.06f);
        ImageView iv = cover(c, sizeDp, round ? -1 : 10);
        Img.load(iv, coverUrl, dp(sizeDp));
        box.addView(iv);
        TextView t = oneLine(text(c, title == null ? "" : title, 15, TEXT, semibold));
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(dp(sizeDp), ViewGroup.LayoutParams.WRAP_CONTENT);
        tp.topMargin = dp(8);
        box.addView(t, tp);
        if (subtitle != null) {
            TextView s = oneLine(text(c, subtitle, 13, MUTED, regular));
            box.addView(s, new LinearLayout.LayoutParams(dp(sizeDp), ViewGroup.LayoutParams.WRAP_CONTENT));
        }
        box.setOnClickListener(v -> onClick.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.rightMargin = dp(10);
        box.setLayoutParams(lp);
        return box;
    }

    /** Ligne de morceau (numero ou pochette, titre, artiste, duree, coeur). */
    static View trackRow(Context c, Track t, int number, boolean withCover, Runnable onClick) {
        LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(12), dp(7), dp(16), dp(7));
        focusable(row, 12, true, 1.0f);

        if (withCover) {
            ImageView iv = cover(c, 48, 6);
            Img.load(iv, t.coverUrl, dp(48));
            row.addView(iv);
        } else {
            TextView n = text(c, String.valueOf(number), 16, MUTED, regular);
            n.setGravity(Gravity.CENTER);
            row.addView(n, new LinearLayout.LayoutParams(dp(40), ViewGroup.LayoutParams.WRAP_CONTENT));
        }

        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        TextView title = oneLine(text(c, t.title, 17, TEXT, semibold));
        col.addView(title);
        String sub = t.artist == null ? "" : t.artist;
        if (withCover && t.album != null) sub += "  ·  " + t.album;
        TextView artist = oneLine(text(c, sub, 14, MUTED, regular));
        col.addView(artist);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        cp.leftMargin = dp(14);
        row.addView(col, cp);

        TextView d = text(c, duration(t.duration), 14, MUTED, regular);
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
