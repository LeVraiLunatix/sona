package fr.lunatix.alyra;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.json.JSONArray;
import org.json.JSONObject;

import fr.lunatix.alyra.Models.*;

/** Client de l'API privee de Sona (Bearer API_TOKEN), appels synchrones a lancer hors thread UI. */
final class Api {
    private Api() {}

    static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final ExecutorService POOL = Executors.newFixedThreadPool(4);
    private static SharedPreferences prefs;
    static String base = "";
    static String token = "";

    static void init(Context c) {
        prefs = c.getApplicationContext().getSharedPreferences("alyra", Context.MODE_PRIVATE);
        base = prefs.getString("url", "");
        token = prefs.getString("token", "");
    }

    static void save(String url, String tok) {
        base = url.trim().replaceAll("/+$", "");
        token = tok.trim();
        prefs.edit().putString("url", base).putString("token", token).apply();
    }

    static boolean configured() { return !base.isEmpty() && !token.isEmpty(); }

    // ---- asynchrone -------------------------------------------------------

    interface Done<T> { void ok(T value); }
    interface Fail { void err(String message); }

    static <T> void async(Callable<T> work, Done<T> ok, Fail fail) {
        POOL.execute(() -> {
            try {
                T v = work.call();
                MAIN.post(() -> ok.ok(v));
            } catch (Exception e) {
                String m = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                MAIN.post(() -> fail.err(m));
            }
        });
    }

    // ---- HTTP -------------------------------------------------------------

    static HttpURLConnection open(String method, String path, int readTimeoutMs) throws IOException {
        if (base.isEmpty()) throw new IOException("Serveur non configure");
        HttpURLConnection c = (HttpURLConnection) new URL(base + path).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(8000);
        c.setReadTimeout(readTimeoutMs);
        c.setRequestProperty("Authorization", "Bearer " + token);
        c.setRequestProperty("Accept", "application/json");
        return c;
    }

    private static String read(HttpURLConnection c) throws IOException {
        int code = c.getResponseCode();
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        if (in != null) {
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) buf.write(b, 0, n);
            in.close();
        }
        String body = buf.toString("UTF-8");
        if (code >= 400) {
            String detail = body;
            try { detail = new JSONObject(body).optString("detail", body); } catch (Exception ignored) {}
            if (code == 401) detail = "Jeton refuse par le serveur";
            throw new IOException(detail.isEmpty() ? "HTTP " + code : detail);
        }
        return body;
    }

    static String get(String path) throws IOException {
        HttpURLConnection c = open("GET", path, 30000);
        try { return read(c); } finally { c.disconnect(); }
    }

    static void send(String method, String path, JSONObject body) throws IOException {
        HttpURLConnection c = open(method, path, 30000);
        try {
            if (body != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                OutputStream os = c.getOutputStream();
                os.write(body.toString().getBytes("UTF-8"));
                os.close();
            }
            read(c);
        } finally { c.disconnect(); }
    }

    static String enc(String s) {
        try { return URLEncoder.encode(s, "UTF-8"); } catch (Exception e) { return s; }
    }

    static JSONArray arr(String s) throws Exception { return new JSONArray(s); }

    // ---- endpoints --------------------------------------------------------

    static class SearchResult {
        List<Track> tracks = new ArrayList<>();
        String queryId;
        int total;
    }

    static SearchResult search(String q, String queryId, int offset) throws Exception {
        String path = "/search?limit=20&offset=" + offset
                + (queryId != null ? "&query_id=" + enc(queryId) : "&q=" + enc(q));
        JSONObject o = new JSONObject(get(path));
        SearchResult r = new SearchResult();
        r.queryId = o.optString("query_id");
        r.total = o.optInt("total");
        r.tracks = Track.list(o.optJSONArray("tracks"));
        return r;
    }

    static List<Artist> searchArtists(String q) throws Exception {
        return Artist.list(arr(get("/search/artists?limit=12&q=" + enc(q))));
    }

    static List<Album> searchAlbums(String q) throws Exception {
        return Album.list(arr(get("/search/albums?limit=12&q=" + enc(q))));
    }

    static Album album(String source, String id) throws Exception {
        return Album.from(new JSONObject(get("/albums/" + source + "/" + enc(id))));
    }

    static Album playlist(String source, String id) throws Exception {
        return Album.from(new JSONObject(get("/playlists/" + source + "/" + enc(id))));
    }

    static Artist artist(String source, String id) throws Exception {
        return Artist.from(new JSONObject(get("/artists/" + source + "/" + enc(id))));
    }

    static List<Track> topTracks(String source, String id) throws Exception {
        return Track.list(arr(get("/artists/" + source + "/" + enc(id) + "/top-tracks")));
    }

    static List<Track> artistRadio(String source, String id) throws Exception {
        return Track.list(arr(get("/artists/" + source + "/" + enc(id) + "/radio")));
    }

    static List<Artist> relatedArtists(String source, String id) throws Exception {
        return Artist.list(arr(get("/artists/" + source + "/" + enc(id) + "/related")));
    }

    /** [0] = albums, [1] = singles */
    static List<List<Album>> artistAlbums(String source, String id) throws Exception {
        JSONObject o = new JSONObject(get("/artists/" + source + "/" + enc(id) + "/albums"));
        List<List<Album>> out = new ArrayList<>();
        out.add(Album.list(o.optJSONArray("albums")));
        out.add(Album.list(o.optJSONArray("singles")));
        return out;
    }

    static List<Entry> library(String kind, int offset, int limit) throws Exception {
        JSONObject o = new JSONObject(get("/library/" + kind + "?offset=" + offset + "&limit=" + limit));
        return Entry.list(o.optJSONArray("items"), kind);
    }

    static List<Entry> history(int limit) throws Exception {
        JSONObject o = new JSONObject(get("/history?limit=" + limit));
        return Entry.list(o.optJSONArray("items"), "track");
    }

    static List<RadioGroup> radios() throws Exception {
        JSONArray a = arr(get("/browse/radios"));
        List<RadioGroup> out = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) {
            JSONObject g = a.getJSONObject(i);
            RadioGroup rg = new RadioGroup();
            rg.title = g.optString("title");
            JSONArray rs = g.optJSONArray("radios");
            for (int j = 0; rs != null && j < rs.length(); j++) {
                JSONObject r = rs.getJSONObject(j);
                Radio ra = new Radio();
                ra.id = r.optString("id");
                ra.title = r.optString("title");
                ra.pictureUrl = str(r, "picture_url");
                rg.radios.add(ra);
            }
            out.add(rg);
        }
        return out;
    }

    private static String str(JSONObject o, String k) { return Models.str(o, k); }

    static List<Track> radioTracks(String id) throws Exception {
        return Track.list(arr(get("/radios/" + enc(id) + "/tracks")));
    }

    /** Resout un lien colle : renvoie l'objet JSON {kind, track|album|artist}. */
    static JSONObject resolve(String text) throws Exception {
        HttpURLConnection c = open("POST", "/resolve", 30000);
        try {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            OutputStream os = c.getOutputStream();
            os.write(new JSONObject().put("text", text).toString().getBytes("UTF-8"));
            os.close();
            return new JSONObject(read(c));
        } finally { c.disconnect(); }
    }

    // ---- bibliotheque : ensemble des morceaux aimes ----------------------

    private static final Set<String> LIKED = new HashSet<>();

    static void loadLiked() throws Exception {
        Set<String> s = new HashSet<>();
        for (int off = 0; off < 1000; off += 100) {
            List<Entry> page = library("track", off, 100);
            for (Entry e : page) s.add(e.source + ":" + e.sourceId);
            if (page.size() < 100) break;
        }
        synchronized (LIKED) { LIKED.clear(); LIKED.addAll(s); }
    }

    static boolean isLiked(String key) { synchronized (LIKED) { return LIKED.contains(key); } }

    static void setLiked(Track t, boolean like) throws Exception {
        if (like) {
            send("POST", "/library/track", new JSONObject().put("source", t.source).put("source_id", t.sourceId));
            synchronized (LIKED) { LIKED.add(t.key()); }
        } else {
            send("DELETE", "/library/track/" + t.source + "/" + enc(t.sourceId), null);
            synchronized (LIKED) { LIKED.remove(t.key()); }
        }
    }
}
