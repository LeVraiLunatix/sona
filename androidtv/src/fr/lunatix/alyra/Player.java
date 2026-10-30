package fr.lunatix.alyra;

import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.MediaMetadata;
import android.media.MediaPlayer;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import fr.lunatix.alyra.Models.Track;

/**
 * Lecteur unique de l'appli. Le serveur telecharge/verifie le morceau a la
 * demande (parfois 10-20 s) : on recupere donc le fichier en entier dans le
 * cache disque avant de lancer MediaPlayer, et on prechauffe le suivant.
 */
final class Player {
    static final Player I = new Player();

    interface Listener { void onChange(); }

    static final int IDLE = 0, LOADING = 1, PLAYING = 2, PAUSED = 3, ERROR = 4;

    private Context app;
    private MediaPlayer mp;
    private MediaSession session;
    private final List<Track> queue = new ArrayList<>();
    private int index = -1;
    private int state = IDLE;
    private String error;
    private int gen;
    private Callable<List<Track>> refill; // radio : redemande des morceaux quand la file se vide
    private final List<Listener> listeners = new ArrayList<>();
    private final ExecutorService io = Executors.newFixedThreadPool(2);
    private File cacheDir;
    String repeat = "off";          // off | all | one (piloté aussi par Connect)
    boolean shuffle;
    boolean claim;                  // lecture lancée à la main : Connect met les autres appareils en pause
    private int pendingSeekMs;
    volatile org.json.JSONObject connectState; // état à envoyer à Connect (null : rien ne joue)
    volatile long connectAt;
    volatile float connectPos;
    volatile boolean connectPaused;
    volatile int windowStart;

    private final Runnable ticker = this::tick;

    private void tick() {
        if (state == PLAYING) {
            fire();
            Api.MAIN.postDelayed(ticker, 500);
        }
    }

    void init(Context c) {
        if (app != null) return;
        app = c.getApplicationContext();
        cacheDir = new File(app.getCacheDir(), "audio");
        cacheDir.mkdirs();
        session = new MediaSession(app, "Alyra");
        session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
        session.setCallback(new SessionCb());
        session.setActive(true);
    }

    private static final class SessionCb extends MediaSession.Callback {
        @Override public void onPlay() { I.resume(); }
        @Override public void onPause() { I.pause(); }
        @Override public void onSkipToNext() { I.next(); }
        @Override public void onSkipToPrevious() { I.previous(); }
        @Override public void onSeekTo(long pos) { I.seekTo((int) pos); }
    }

    // ---- etat -------------------------------------------------------------

    void addListener(Listener l) { if (!listeners.contains(l)) listeners.add(l); }
    void removeListener(Listener l) { listeners.remove(l); }

    private void fire() {
        for (Listener l : new ArrayList<>(listeners)) l.onChange();
    }

    Track current() { return index >= 0 && index < queue.size() ? queue.get(index) : null; }
    int state() { return state; }
    String error() { return error; }
    boolean isPlaying() { return state == PLAYING; }
    List<Track> queue() { return queue; }
    int index() { return index; }
    boolean hasNext() { return index + 1 < queue.size() || refill != null; }
    boolean hasPrevious() { return index > 0; }

    int position() {
        try { return mp != null && (state == PLAYING || state == PAUSED) ? mp.getCurrentPosition() : 0; }
        catch (IllegalStateException e) { return 0; }
    }

    int duration() {
        try {
            if (mp != null && (state == PLAYING || state == PAUSED)) return mp.getDuration();
        } catch (IllegalStateException ignored) {}
        Track t = current();
        return t == null ? 0 : t.duration * 1000;
    }

    // ---- commandes --------------------------------------------------------

    void play(List<Track> tracks, int start) { playQueue(tracks, start, null); }

    void playQueue(List<Track> tracks, int start, Callable<List<Track>> more) {
        claim = true;
        playQueueAt(tracks, start, more, 0);
    }

    /** Lance une file ; `seekMs` : reprise à cette position (Connect : « écoute ici »). */
    void playQueueAt(List<Track> tracks, int start, Callable<List<Track>> more, int seekMs) {
        if (tracks.isEmpty()) return;
        pendingSeekMs = seekMs;
        queue.clear();
        queue.addAll(tracks);
        index = Math.max(0, Math.min(start, queue.size() - 1));
        refill = more;
        startCurrent();
    }

    void toggle() {
        if (state == PLAYING) pause();
        else if (state == PAUSED) resume();
        else if (state == ERROR && current() != null) startCurrent();
    }

    void pause() {
        if (mp != null && state == PLAYING) {
            mp.pause();
            state = PAUSED;
            publish();
        }
    }

    void resume() {
        if (mp != null && state == PAUSED) {
            mp.start();
            state = PLAYING;
            Api.MAIN.postDelayed(ticker, 500);
            publish();
        }
    }

    void next() {
        if (index + 1 < queue.size()) {
            index++;
            startCurrent();
        } else if (refill == null && "all".equals(repeat) && !queue.isEmpty()) {
            index = 0;
            startCurrent();
        } else if (refill != null) {
            final int g = ++gen;
            state = LOADING;
            publish();
            Api.async(refill, more -> {
                if (g != gen || more.isEmpty()) return;
                queue.addAll(more);
                index++;
                startCurrent();
            }, msg -> {
                if (g != gen) return;
                fail("Radio : " + msg);
            });
        }
    }

    void previous() {
        if (position() > 4000 || index <= 0) {
            seekTo(0);
        } else {
            index--;
            startCurrent();
        }
    }

    void seekTo(int ms) {
        if (mp != null && (state == PLAYING || state == PAUSED)) {
            mp.seekTo(Math.max(0, Math.min(ms, mp.getDuration())));
            publish();
        }
    }

    void seekBy(int deltaMs) { seekTo(position() + deltaMs); }

    // ---- lecture ----------------------------------------------------------

    private void startCurrent() {
        final Track t = current();
        if (t == null) return;
        final int g = ++gen;
        releasePlayer();
        state = LOADING;
        error = null;
        publish();
        io.execute(() -> {
            try {
                File f = fetch(t, g);
                Api.MAIN.post(() -> { if (g == gen) prepare(f, g); });
            } catch (Exception e) {
                String m = e.getMessage() == null ? "Lecture impossible" : e.getMessage();
                Api.MAIN.post(() -> { if (g == gen) fail(m); });
            }
        });
    }

    private void prepare(File f, int g) {
        try {
            mp = new MediaPlayer();
            mp.setDataSource(f.getPath());
            mp.setOnPreparedListener(p -> {
                if (g != gen) return;
                if (pendingSeekMs > 0) { p.seekTo(pendingSeekMs); pendingSeekMs = 0; }
                p.start();
                state = PLAYING;
                Api.MAIN.postDelayed(ticker, 500);
                publish();
                prefetchNext();
            });
            mp.setOnCompletionListener(p -> {
                android.util.Log.w("Alyra", "fin: pos=" + p.getCurrentPosition() + " dur=" + p.getDuration());
                if (g == gen) onEnded();
            });
            mp.setOnErrorListener((p, what, extra) -> {
                android.util.Log.w("Alyra", "erreur MediaPlayer what=" + what + " extra=" + extra);
                if (g == gen) {
                    f.delete(); // fichier corrompu : on le retelechargera
                    fail("Lecture audio impossible");
                }
                return true;
            });
            mp.prepareAsync();
        } catch (Exception e) {
            fail("Lecture audio impossible");
        }
    }

    private void onEnded() {
        if ("one".equals(repeat) && mp != null) {
            mp.seekTo(0);
            mp.start();
            publish();
        } else if (hasNext() || ("all".equals(repeat) && !queue.isEmpty())) next();
        else {
            state = PAUSED;
            publish();
        }
    }

    // ---- options pilotables a distance (Connect) -------------------------

    /** Republie l'etat (ex. apres un « j'aime » venu d'un autre appareil). */
    void touch() { publish(); }

    void setRepeat(String mode) {
        repeat = "all".equals(mode) || "one".equals(mode) ? mode : "off";
        publish();
    }

    void setShuffle(boolean on) {
        shuffle = on;
        if (on && index + 2 < queue.size()) { // melange seulement ce qui reste a jouer
            List<Track> rest = new ArrayList<>(queue.subList(index + 1, queue.size()));
            java.util.Collections.shuffle(rest);
            for (int i = 0; i < rest.size(); i++) queue.set(index + 1 + i, rest.get(i));
        }
        publish();
    }

    void playIndex(int i) {
        if (i < 0 || i >= queue.size()) return;
        index = i;
        startCurrent();
    }

    /** Volume media de la TV, entre 0 et 1. */
    float volume() {
        android.media.AudioManager am = (android.media.AudioManager) app.getSystemService(Context.AUDIO_SERVICE);
        int max = am.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC);
        return max <= 0 ? 0f : am.getStreamVolume(android.media.AudioManager.STREAM_MUSIC) / (float) max;
    }

    void setVolume(float v) {
        android.media.AudioManager am = (android.media.AudioManager) app.getSystemService(Context.AUDIO_SERVICE);
        int max = am.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC);
        am.setStreamVolume(android.media.AudioManager.STREAM_MUSIC, Math.round(Math.max(0f, Math.min(1f, v)) * max), 0);
        publish();
    }

    private void fail(String msg) {
        releasePlayer();
        state = ERROR;
        error = msg;
        publish();
    }

    private void releasePlayer() {
        Api.MAIN.removeCallbacks(ticker);
        if (mp != null) {
            try { mp.release(); } catch (Exception ignored) {}
            mp = null;
        }
    }

    // ---- cache disque -----------------------------------------------------

    private File fileFor(Track t) {
        String safe = (t.source + "_" + t.sourceId).replaceAll("[^A-Za-z0-9_-]", "_");
        return new File(cacheDir, safe + "_mp3.audio");
    }

    private void prefetchNext() {
        if (index + 1 >= queue.size()) return;
        final Track n = queue.get(index + 1);
        final int g = gen;
        io.execute(() -> {
            try { fetch(n, g); } catch (Exception ignored) {}
        });
    }

    private File fetch(Track t, int g) throws IOException {
        File dest = fileFor(t);
        if (dest.isFile() && dest.length() > 0) {
            dest.setLastModified(System.currentTimeMillis());
            return dest;
        }
        synchronized (this) { // un seul telechargement a la fois pour le meme morceau
            if (dest.isFile() && dest.length() > 0) return dest;
            File tmp = new File(dest.getPath() + ".part");
            // MP3 impose : sur cette TV (MediaTek, decodeur "passthrough") le m4a/AAC est lu comme fini
            // apres quelques ms, alors que le MP3 passe.
            String q = "/stream/" + t.source + "/" + Api.enc(t.sourceId) + "?quality=best&format=mp3";
            HttpURLConnection c = Api.open("GET", q, 150000);
            c.setRequestProperty("Accept", "*/*");
            try {
                int code = c.getResponseCode();
                if (code >= 400) {
                    String detail = "Serveur : HTTP " + code;
                    if (code == 404) detail = "Morceau introuvable";
                    if (code == 401) detail = "Jeton refuse par le serveur";
                    if (code == 502) detail = "Source audio indisponible";
                    throw new IOException(detail);
                }
                InputStream in = c.getInputStream();
                FileOutputStream out = new FileOutputStream(tmp);
                byte[] b = new byte[32768];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
                out.close();
                in.close();
            } finally { c.disconnect(); }
            if (!tmp.renameTo(dest)) throw new IOException("Cache audio inaccessible");
            trimCache();
            return dest;
        }
    }

    private void trimCache() {
        File[] files = cacheDir.listFiles();
        if (files == null) return;
        long total = 0;
        for (File f : files) total += f.length();
        long cap = 48L * 1024 * 1024; // la TV n'a que ~4 Go de stockage interne, presque plein
        if (total <= cap) return;
        java.util.Arrays.sort(files, (a, b) -> Long.compare(a.lastModified(), b.lastModified()));
        for (File f : files) {
            if (total <= cap) break;
            Track cur = current();
            if (cur != null && f.equals(fileFor(cur))) continue;
            total -= f.length();
            f.delete();
        }
    }

    // ---- publication (UI, MediaSession, service) --------------------------

    private void publish() {
        fire();
        if (session == null) return;
        Track t = current();
        if (t != null) {
            session.setMetadata(new MediaMetadata.Builder()
                    .putString(MediaMetadata.METADATA_KEY_TITLE, t.title)
                    .putString(MediaMetadata.METADATA_KEY_ARTIST, t.artist)
                    .putString(MediaMetadata.METADATA_KEY_ALBUM, t.album)
                    .putLong(MediaMetadata.METADATA_KEY_DURATION, duration())
                    .build());
        }
        int s;
        switch (state) {
            case PLAYING: s = PlaybackState.STATE_PLAYING; break;
            case PAUSED: s = PlaybackState.STATE_PAUSED; break;
            case LOADING: s = PlaybackState.STATE_BUFFERING; break;
            case ERROR: s = PlaybackState.STATE_ERROR; break;
            default: s = PlaybackState.STATE_NONE;
        }
        long actions = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE | PlaybackState.ACTION_PLAY_PAUSE
                | PlaybackState.ACTION_SKIP_TO_NEXT | PlaybackState.ACTION_SKIP_TO_PREVIOUS | PlaybackState.ACTION_SEEK_TO;
        session.setPlaybackState(new PlaybackState.Builder()
                .setActions(actions).setState(s, position(), state == PLAYING ? 1f : 0f).build());

        if (state == LOADING || state == PLAYING || state == PAUSED) {
            Intent i = new Intent(app, PlayerService.class);
            if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(i);
            else app.startService(i);
        }
        updateConnect();
    }

    /** Prepare l'etat envoye a Sona Connect : une fenetre de la file autour du titre courant. */
    private void updateConnect() {
        Track cur = current();
        if (cur == null || state == IDLE) {
            connectState = null;
            Connect.I.kick();
            return;
        }
        try {
            int start = Math.max(0, index - 3);
            int end = Math.min(queue.size(), start + 60);
            org.json.JSONArray q = new org.json.JSONArray();
            for (int i = start; i < end; i++) q.put(queue.get(i).toJson());
            org.json.JSONObject o = new org.json.JSONObject();
            o.put("queue", q);
            o.put("index", index - start);
            o.put("volume", volume());
            o.put("shuffle", shuffle);
            o.put("repeat", repeat);
            o.put("liked", Api.isLiked(cur.key()));
            windowStart = start;
            connectPaused = state == PAUSED || state == ERROR;
            connectPos = position() / 1000f;
            connectAt = System.currentTimeMillis();
            connectState = o;
        } catch (Exception ignored) {
            connectState = null;
        }
        Connect.I.kick();
    }

    MediaSession.Token sessionToken() { return session.getSessionToken(); }
}
