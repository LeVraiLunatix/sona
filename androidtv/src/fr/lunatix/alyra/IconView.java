package fr.lunatix.alyra;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.View;

/** Pictogrammes de transport dessines au Path (la police de la TV n'a pas les symboles media). */
final class IconView extends View {
    static final int PLAY = 0, PAUSE = 1, NEXT = 2, PREV = 3, HEART = 4, HEART_ON = 5, LOADING = 6;

    private int type;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();

    IconView(Context c, int type, int sizeDp, boolean accent) {
        super(c);
        this.type = type;
        setMinimumWidth(UI.dp(sizeDp));
        setMinimumHeight(UI.dp(sizeDp));
        StateListDrawable sl = new StateListDrawable();
        GradientDrawable on = new GradientDrawable();
        on.setShape(GradientDrawable.OVAL);
        on.setColor(0xFF2F3A3E);
        on.setStroke(UI.dp(2), UI.CYAN);
        GradientDrawable off = new GradientDrawable();
        off.setShape(GradientDrawable.OVAL);
        off.setColor(accent ? UI.CYAN : UI.RAISED);
        sl.addState(new int[]{android.R.attr.state_focused}, on);
        sl.addState(new int[]{}, off);
        setBackground(sl);
        setFocusable(true);
        setClickable(true);
        this.accent = accent;
        setOnFocusChangeListener((x, has) ->
                x.animate().scaleX(has ? 1.1f : 1f).scaleY(has ? 1.1f : 1f).setDuration(120).start());
    }

    private final boolean accent;

    void setType(int t) {
        if (t != type) {
            type = t;
            invalidate();
        }
    }

    @Override protected void onMeasure(int w, int h) {
        setMeasuredDimension(getSuggestedMinimumWidth(), getSuggestedMinimumHeight());
    }

    @Override protected void onDraw(Canvas c) {
        int w = getWidth(), h = getHeight();
        int s = Math.min(w, h);
        c.save();
        c.translate((w - s) / 2f, (h - s) / 2f);
        paint.setStyle(Paint.Style.FILL);
        int fg = (accent && !isFocused()) ? UI.BG : UI.TEXT;
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
                    paint.setColor(UI.MAGENTA);
                    c.drawPath(path, paint);
                } else {
                    paint.setStyle(Paint.Style.STROKE);
                    paint.setStrokeWidth(.055f * s);
                    c.drawPath(path, paint);
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
