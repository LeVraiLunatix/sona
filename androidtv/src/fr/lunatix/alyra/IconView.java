package fr.lunatix.alyra;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.View;

/** Pictogrammes dessines au Path (transport, navigation) : la police de la TV n'a pas ces symboles. */
final class IconView extends View {
    static final int PLAY = 0, PAUSE = 1, NEXT = 2, PREV = 3, HEART = 4, HEART_ON = 5, LOADING = 6,
            HOME = 7, SEARCH = 8, LIBRARY = 9, RADIO = 10, SETTINGS = 11;

    private int type;
    private int tint = UI.TEXT;
    private final boolean accent;
    private final boolean plain;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final RectF rect = new RectF();

    /** Bouton rond focalisable. */
    IconView(Context c, int type, int sizeDp, boolean accent) {
        super(c);
        this.type = type;
        this.accent = accent;
        this.plain = false;
        setMinimumWidth(UI.dp(sizeDp));
        setMinimumHeight(UI.dp(sizeDp));
        StateListDrawable sl = new StateListDrawable();
        GradientDrawable on = new GradientDrawable();
        on.setShape(GradientDrawable.OVAL);
        on.setColor(accent ? 0xFFFFFFFF : UI.FILL_FOCUS);
        on.setStroke(UI.dp(3), accent ? UI.ACCENT2 : UI.ACCENT);
        GradientDrawable off = new GradientDrawable();
        off.setShape(GradientDrawable.OVAL);
        off.setColor(accent ? 0xE6F4F6F8 : UI.FILL_STRONG);
        sl.addState(new int[]{android.R.attr.state_focused}, on);
        sl.addState(new int[]{}, off);
        setBackground(sl);
        setFocusable(true);
        setClickable(true);
        setOnFocusChangeListener((x, has) ->
                x.animate().scaleX(has ? 1.1f : 1f).scaleY(has ? 1.1f : 1f).setDuration(120).start());
    }

    /** Glyphe seul (menu) : ni fond, ni focus. */
    IconView(Context c, int type, int sizeDp, int tint) {
        super(c);
        this.type = type;
        this.tint = tint;
        this.accent = false;
        this.plain = true;
        setMinimumWidth(UI.dp(sizeDp));
        setMinimumHeight(UI.dp(sizeDp));
    }

    void setType(int t) {
        if (t != type) {
            type = t;
            invalidate();
        }
    }

    void setTint(int c) {
        if (c != tint) {
            tint = c;
            invalidate();
        }
    }

    @Override protected void onMeasure(int w, int h) {
        setMeasuredDimension(getSuggestedMinimumWidth(), getSuggestedMinimumHeight());
    }

    @Override protected void onDraw(Canvas c) {
        int w = getWidth(), h = getHeight();
        float s = Math.min(w, h);
        c.save();
        c.translate((w - s) / 2f, (h - s) / 2f);
        paint.setStyle(Paint.Style.FILL);
        int fg = plain ? tint : (accent ? UI.ON_ACCENT : UI.TEXT);
        paint.setColor(fg);
        path.reset();
        switch (type) {
            case PLAY:
                path.moveTo(.38f * s, .27f * s);
                path.lineTo(.38f * s, .73f * s);
                path.lineTo(.74f * s, .5f * s);
                path.close();
                c.drawPath(path, paint);
                break;
            case PAUSE:
                c.drawRoundRect(.33f * s, .27f * s, .45f * s, .73f * s, .02f * s, .02f * s, paint);
                c.drawRoundRect(.55f * s, .27f * s, .67f * s, .73f * s, .02f * s, .02f * s, paint);
                break;
            case NEXT:
                path.moveTo(.30f * s, .30f * s);
                path.lineTo(.30f * s, .70f * s);
                path.lineTo(.62f * s, .5f * s);
                path.close();
                c.drawPath(path, paint);
                c.drawRect(.66f * s, .30f * s, .72f * s, .70f * s, paint);
                break;
            case PREV:
                path.moveTo(.70f * s, .30f * s);
                path.lineTo(.70f * s, .70f * s);
                path.lineTo(.38f * s, .5f * s);
                path.close();
                c.drawPath(path, paint);
                c.drawRect(.28f * s, .30f * s, .34f * s, .70f * s, paint);
                break;
            case HEART:
            case HEART_ON:
                heart(s);
                if (type == HEART_ON) {
                    paint.setColor(plain ? tint : UI.ACCENT);
                    c.drawPath(path, paint);
                } else {
                    paint.setStyle(Paint.Style.STROKE);
                    paint.setStrokeWidth(.055f * s);
                    c.drawPath(path, paint);
                }
                break;
            case HOME:
                path.moveTo(.5f * s, .18f * s);
                path.lineTo(.84f * s, .46f * s);
                path.lineTo(.84f * s, .82f * s);
                path.lineTo(.62f * s, .82f * s);
                path.lineTo(.62f * s, .58f * s);
                path.lineTo(.38f * s, .58f * s);
                path.lineTo(.38f * s, .82f * s);
                path.lineTo(.16f * s, .82f * s);
                path.lineTo(.16f * s, .46f * s);
                path.close();
                c.drawPath(path, paint);
                break;
            case SEARCH:
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(.09f * s);
                paint.setStrokeCap(Paint.Cap.ROUND);
                c.drawCircle(.44f * s, .44f * s, .22f * s, paint);
                c.drawLine(.61f * s, .61f * s, .82f * s, .82f * s, paint);
                paint.setStrokeCap(Paint.Cap.BUTT);
                break;
            case LIBRARY:
                c.drawRoundRect(.18f * s, .2f * s, .30f * s, .8f * s, .02f * s, .02f * s, paint);
                c.drawRoundRect(.38f * s, .2f * s, .50f * s, .8f * s, .02f * s, .02f * s, paint);
                c.save();
                c.rotate(-14f, .68f * s, .5f * s);
                c.drawRoundRect(.62f * s, .2f * s, .74f * s, .8f * s, .02f * s, .02f * s, paint);
                c.restore();
                break;
            case RADIO:
                c.drawCircle(.5f * s, .5f * s, .10f * s, paint);
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(.07f * s);
                rect.set(.22f * s, .22f * s, .78f * s, .78f * s);
                c.drawArc(rect, -50, 100, false, paint);
                c.drawArc(rect, 130, 100, false, paint);
                rect.set(.10f * s, .10f * s, .90f * s, .90f * s);
                c.drawArc(rect, -45, 90, false, paint);
                c.drawArc(rect, 135, 90, false, paint);
                break;
            case SETTINGS:
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(.09f * s);
                c.drawCircle(.5f * s, .5f * s, .17f * s, paint);
                paint.setStyle(Paint.Style.FILL);
                for (int i = 0; i < 8; i++) {
                    c.save();
                    c.rotate(i * 45f, .5f * s, .5f * s);
                    c.drawRoundRect(.45f * s, .12f * s, .55f * s, .26f * s, .02f * s, .02f * s, paint);
                    c.restore();
                }
                break;
            default: // LOADING : trois points
                for (int i = 0; i < 3; i++) c.drawCircle((.36f + i * .14f) * s, .5f * s, .04f * s, paint);
        }
        c.restore();
    }

    private void heart(float s) {
        path.moveTo(.5f * s, .76f * s);
        path.cubicTo(.20f * s, .54f * s, .24f * s, .28f * s, .39f * s, .28f * s);
        path.cubicTo(.45f * s, .28f * s, .5f * s, .33f * s, .5f * s, .37f * s);
        path.cubicTo(.5f * s, .33f * s, .55f * s, .28f * s, .61f * s, .28f * s);
        path.cubicTo(.76f * s, .28f * s, .80f * s, .54f * s, .5f * s, .76f * s);
        path.close();
    }
}
