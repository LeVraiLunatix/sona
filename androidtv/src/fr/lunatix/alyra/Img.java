package fr.lunatix.alyra;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.LruCache;
import android.widget.ImageView;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Chargeur d'images minimal : cache memoire LRU, decodage reduit, 3 fils. */
final class Img {
    private Img() {}

    private static final ExecutorService POOL = Executors.newFixedThreadPool(3);
    // par nombre d'entrees (sizeOf en sous-classe genere un pont generique que d8 ne digere pas)
    private static final LruCache<String, Bitmap> CACHE = new LruCache<>(70);

    static void load(ImageView v, String url, int targetPx) {
        v.setTag(url);
        if (url == null) { v.setImageDrawable(null); return; }
        String key = url + "@" + targetPx;
        Bitmap hit = CACHE.get(key);
        if (hit != null) { v.setImageBitmap(hit); return; }
        v.setImageDrawable(null);
        POOL.execute(() -> {
            Bitmap b = fetch(url, targetPx);
            if (b == null) return;
            CACHE.put(key, b);
            Api.MAIN.post(() -> {
                if (url.equals(v.getTag())) v.setImageBitmap(b);
            });
        });
    }

    /** Couleur dominante d'une image (teinte du lecteur plein ecran), calculee hors thread UI. */
    static void dominant(String url, Api.Done<Integer> done) {
        if (url == null) return;
        POOL.execute(() -> {
            Bitmap b = fetch(url, 24);
            if (b == null) return;
            Bitmap one = Bitmap.createScaledBitmap(b, 1, 1, true);
            int px = one.getPixel(0, 0);
            float[] hsv = new float[3];
            android.graphics.Color.colorToHSV(px, hsv);
            hsv[1] = Math.min(1f, hsv[1] * 1.15f);
            hsv[2] = Math.max(hsv[2], 0.55f);
            int out = android.graphics.Color.HSVToColor(hsv);
            Api.MAIN.post(() -> done.ok(out));
        });
    }

    /** Pour les besoins hors vue (ex. vignette de notification). */
    static Bitmap fetch(String url, int targetPx) {
        try {
            String u = url.startsWith("http://") ? "https://" + url.substring(7) : url;
            HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(15000);
            InputStream in = c.getInputStream();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] tmp = new byte[16384];
            int n;
            while ((n = in.read(tmp)) > 0) buf.write(tmp, 0, n);
            in.close();
            byte[] data = buf.toByteArray();
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(data, 0, data.length, o);
            int s = 1;
            while (o.outWidth / (s * 2) >= targetPx) s *= 2;
            o = new BitmapFactory.Options();
            o.inSampleSize = s;
            return BitmapFactory.decodeByteArray(data, 0, data.length, o);
        } catch (Exception e) {
            return null;
        }
    }
}
