package fr.lunatix.alyra;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import org.json.JSONArray;
import org.json.JSONObject;

import fr.lunatix.alyra.Models.Track;

/**
 * Sona Connect (voir app/services/connect.py) : la TV se signale au serveur avec son etat de
 * lecture et recoit les commandes des autres appareils (telephone, PC) : lecture/pause, suivant,
 * position, volume, aleatoire, repeter, j'aime, « ecoute ici »... Une longue attente (wait) sert
 * de canal de commande quasi instantane ; chaque changement local declenche aussi un sync tout de suite.
 */
final class Connect {
    static final Connect I = new Connect();

    private static final int WAIT_SECONDS = 8; // < 15 s : au-dela le serveur nous croit hors ligne

    private SharedPreferences prefs;
    private String deviceId;
    private String deviceName;
    private volatile boolean running;
    private volatile JSONObject snapshot;
    private final ExecutorService kicker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean kickPending = new AtomicBoolean(false);
    private boolean registered;
    private int registerTries;

    String deviceId() { return deviceId; }
    String name() { return deviceName == null ? "Android TV" : deviceName; }

    void start(Context c) {
        if (running) return;
        prefs = c.getApplicationContext().getSharedPreferences("alyra", Context.MODE_PRIVATE);
        deviceId = prefs.getString("device_id", null);
        if (deviceId == null) {
            deviceId = "tv-" + UUID.randomUUID().toString().replace("-", "").substring(0, 20);
            prefs.edit().putString("device_id", deviceId).apply();
        }
        String n = null;
        try { n = android.provider.Settings.Global.getString(c.getContentResolver(), "device_name"); }
        catch (Exception ignored) {}
        deviceName = (n == null || n.trim().isEmpty()) ? "Android TV" : n.trim();
        if (deviceName.length() > 60) deviceName = deviceName.substring(0, 60);
        registered = prefs.getBoolean("connect_registered", false);
        running = true;
        Thread t = new Thread(this::loop, "alyra-connect");
        t.setDaemon(true);
        t.start();
    }

    /** Un changement local (titre, pause, position...) : on previent le serveur sans attendre le prochain tour. */
    void kick() {
        if (!running || !Api.configured() || !kickPending.compareAndSet(false, true)) return;
        kicker.execute(() -> {
            kickPending.set(false);
            try { sync(0); } catch (Exception ignored) {}
        });
    }

    private void loop() {
        int fails = 0;
        while (running) {
            if (!Api.configured()) { sleep(3000); continue; }
            try {
                sync(WAIT_SECONDS);
                fails = 0;
            } catch (Exception e) {
                fails++;
                sleep(Math.min(30, 2 << Math.min(fails, 4)) * 1000L);
            }
        }
    }

    private static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
    }

    private void sync(int wait) throws Exception {
        JSONObject body = new JSONObject();
        body.put("device_id", deviceId);
        body.put("name", deviceName);
        body.put("kind", "web");
        body.put("wait", wait);
        JSONObject st = Player.I.connectState;
        if (st != null) {
            JSONObject s = new JSONObject(st.toString()); // copie : l'original peut etre remplace entre-temps
            float pos = Player.I.connectPos;
            if (!Player.I.connectPaused) pos += (System.currentTimeMillis() - Player.I.connectAt) / 1000f;
            s.put("position", Math.max(0, pos));
            s.put("paused", Player.I.connectPaused);
            s.put("name", "");
            body.put("state", s);
            if (Player.I.claim && !Player.I.connectPaused) {
                body.put("claim", true);
                Player.I.claim = false;
            }
        }
        HttpURLConnection c = Api.open("POST", "/connect/sync", (wait + 12) * 1000);
        try {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            OutputStream os = c.getOutputStream();
            os.write(body.toString().getBytes("UTF-8"));
            os.close();
            int code = c.getResponseCode();
            if (code >= 400) throw new java.io.IOException("Connect : HTTP " + code);
            java.io.InputStream in = c.getInputStream();
            java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) buf.write(b, 0, n);
            in.close();
            JSONObject r = new JSONObject(buf.toString("UTF-8"));
            snapshot = r;
            JSONArray cmds = r.optJSONArray("commands");
            for (int i = 0; cmds != null && i < cmds.length(); i++) {
                final JSONObject cmd = cmds.getJSONObject(i);
                Api.MAIN.post(() -> apply(cmd));
            }
        } finally { c.disconnect(); }
        if (!registered) register();
    }

    /** Inscrit la TV dans « Appareils » du telephone/PC pour qu'elle y reste meme eteinte. */
    private void register() {
        registered = true;
        try {
            Api.send("POST", "/connect/saved", new JSONObject().put("device_id", deviceId));
            prefs.edit().putBoolean("connect_registered", true).apply();
        } catch (Exception e) {
            // 409 (liste pleine) ou reseau : on retente quelques fois, sans bloquer la boucle de synchro
            if (++registerTries < 5) registered = false;
        }
    }

    // ---- commandes recues -------------------------------------------------

    private void apply(JSONObject c) {
        Player p = Player.I;
        String action = c.optString("action");
        switch (action) {
            case "play": p.resume(); break;
            case "pause": p.pause(); break;
            case "toggle": p.toggle(); break;
            case "next": p.next(); break;
            case "previous": p.previous(); break;
            case "seek": p.seekTo((int) (c.optDouble("position", 0) * 1000)); break;
            case "volume": p.setVolume((float) c.optDouble("volume", p.volume())); break;
            case "shuffle": p.setShuffle(!p.shuffle); break;
            case "repeat": p.setRepeat("off".equals(p.repeat) ? "all" : "all".equals(p.repeat) ? "one" : "off"); break;
            case "play_index": p.playIndex(p.windowStart + c.optInt("index", 0)); break;
            case "like": {
                Track t = p.current();
                if (t == null) break;
                final boolean like = !Api.isLiked(t.key());
                Api.async(() -> { Api.setLiked(t, like); return true; }, ok -> p.touch(), m -> {});
                break;
            }
            case "transfer":
            case "play_tracks": {
                List<Track> q = Track.list(c.optJSONArray("queue"));
                if (q.isEmpty()) break;
                if ("play_tracks".equals(action)) p.claim = true;
                p.playQueueAt(new ArrayList<>(q), c.optInt("index", 0), null, (int) (c.optDouble("position", 0) * 1000));
                break;
            }
            default: break;
        }
    }

    // ---- ce que la TV peut proposer a l'ecran -----------------------------

    /** Derniere lecture du compte si elle vient d'un autre appareil (« reprendre ici »). */
    List<JSONObject> sessionElsewhere() throws Exception {
        if (snapshot == null) {
            if (!running) return new ArrayList<>();
            sync(0);
        }
        List<JSONObject> out = new ArrayList<>();
        JSONObject s = snapshot == null ? null : snapshot.optJSONObject("session");
        if (s != null && !deviceId.equals(s.optString("device_id")) && s.optJSONObject("track") != null) out.add(s);
        return out;
    }

    /** « Ecoute ici » : la TV reprend la session du compte (file, titre, position). */
    void transferHere() {
        Api.async(() -> {
            Api.send("POST", "/connect/command", new JSONObject()
                    .put("device_id", deviceId).put("target", deviceId).put("action", "transfer"));
            return true;
        }, ok -> kick(), m -> {});
    }
}
