package fr.lunatix.alyra;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

/** Affiche un QR code : plaque blanche arrondie (zone de silence de 4 modules) et modules sombres. */
final class QrView extends View {
    private final QrCode qr;
    private final int sizePx;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rect = new RectF();

    QrView(Context c, String text, int sizeDp) {
        super(c);
        this.qr = QrCode.encode(text);
        this.sizePx = UI.dp(sizeDp);
    }

    @Override protected void onMeasure(int w, int h) { setMeasuredDimension(sizePx, sizePx); }

    @Override protected void onDraw(Canvas c) {
        int total = qr.size + 8;                          // + zone de silence
        float cell = (float) Math.floor(Math.min(getWidth(), getHeight()) / (float) total * 4f) / 4f;
        float offset = (getWidth() - cell * total) / 2f;
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0xFFFFFFFF);
        rect.set(0, 0, getWidth(), getHeight());
        c.drawRoundRect(rect, UI.dp(18), UI.dp(18), paint);
        paint.setColor(0xFF0E1014);
        for (int y = 0; y < qr.size; y++) {
            for (int x = 0; x < qr.size; x++) {
                if (!qr.get(x, y)) continue;
                float left = offset + (x + 4) * cell, top = offset + (y + 4) * cell;
                c.drawRect(left, top, left + cell, top + cell, paint);
            }
        }
    }
}
