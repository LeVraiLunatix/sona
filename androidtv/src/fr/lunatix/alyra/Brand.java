package fr.lunatix.alyra;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Identite alyra. : fond a trois taches de couleur, logo « a » en verre, nom avec son point allume. */
final class Brand {
    private Brand() {}

    /** Fond de l'appli : graphite (#0e1014) + trois taches (bleu, mauve, ambre) comme sur le site. */
    static final class Background extends View {
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        private int tint = 0; // couleur dominante de la pochette (lecteur plein ecran), 0 = aucune

        Background(Context c) { super(c); }

        void setTint(int color) {
            tint = color;
            invalidate();
        }

        @Override protected void onDraw(Canvas c) {
            int w = getWidth(), h = getHeight();
            float vm = Math.max(w, h);
            c.drawColor(UI.BG);
            blob(c, w * 0.06f, -h * 0.10f, vm * 0.62f, tint != 0 ? withAlpha(tint, 0.85f) : 0xD93D5A99);
            blob(c, w * 1.04f, h * 0.12f, vm * 0.58f, tint != 0 ? withAlpha(tint, 0.45f) : 0xB37A4A7E);
            blob(c, w * 0.40f, h * 1.12f, vm * 0.64f, tint != 0 ? withAlpha(tint, 0.30f) : 0x80B98557);
        }

        private static int withAlpha(int rgb, float a) {
            return ((int) (a * 255) << 24) | (rgb & 0xFFFFFF);
        }

        private void blob(Canvas c, float cx, float cy, float r, int color) {
            p.setShader(new RadialGradient(cx, cy, r, color, color & 0x00FFFFFF, Shader.TileMode.CLAMP));
            c.drawCircle(cx, cy, r, p);
            p.setShader(null);
        }
    }

    /** Le « a » en verre (cercle + hampe) et son point allume, dessine sur 64x64 comme #ay-mark du site. */
    static final class Mark extends View {
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int size;

        Mark(Context c, int sizeDp) {
            super(c);
            size = UI.dp(sizeDp);
        }

        @Override protected void onMeasure(int w, int h) { setMeasuredDimension(size, size); }

        @Override protected void onDraw(Canvas c) {
            float k = getWidth() / 64f;
            c.save();
            c.scale(k, k);
            c.translate(-1.1f, -2f);
            p.setStyle(Paint.Style.STROKE);
            p.setStrokeWidth(6f);
            p.setStrokeCap(Paint.Cap.ROUND);
            p.setShader(new LinearGradient(10, 14, 46, 54, 0xE0FFFFFF, 0x4DFFFFFF, Shader.TileMode.CLAMP));
            c.drawCircle(27, 34, 14, p);
            c.drawLine(41, 20, 41, 48, p);
            p.setShader(null);
            // point allume
            p.setStyle(Paint.Style.FILL);
            p.setColor(0x55FFFFFF);
            c.drawCircle(52.6f, 47.4f, 6.2f, p);
            p.setColor(0xFFFFFFFF);
            c.drawCircle(52.6f, 47.4f, 3.6f, p);
            c.restore();
        }
    }

    /** « alyra. » : nom en gras serre, point allume (halo). */
    static View wordmark(Context c, float sp) {
        LinearLayout l = new LinearLayout(c);
        l.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView a = UI.text(c, "alyra", sp, UI.TEXT, UI.bold);
        a.setLetterSpacing(-0.05f);
        TextView dot = UI.text(c, ".", sp, UI.TEXT, UI.bold);
        dot.setShadowLayer(UI.dp(sp * 0.35f), 0, 0, 0xFFFFFFFF);
        l.addView(a);
        l.addView(dot);
        return l;
    }

    /** Logo complet : marque + nom. */
    static View lockup(Context c, int markDp, float sp) {
        LinearLayout l = new LinearLayout(c);
        l.setGravity(android.view.Gravity.CENTER_VERTICAL);
        l.addView(new Mark(c, markDp));
        View w = wordmark(c, sp);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.WRAP_CONTENT, android.view.ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.leftMargin = UI.dp(8);
        l.addView(w, lp);
        return l;
    }
}
