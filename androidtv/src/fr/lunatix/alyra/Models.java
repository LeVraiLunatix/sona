package fr.lunatix.alyra;

import java.util.ArrayList;
import java.util.List;

import org.json.JSONArray;
import org.json.JSONObject;

/** Miroir de app/api/schemas.py cote serveur. */
final class Models {
    private Models() {}

    static String str(JSONObject o, String k) {
        if (o == null || o.isNull(k)) return null;
        String s = o.optString(k, null);
        return (s == null || s.isEmpty()) ? null : s;
    }

    static final class Track {
        String source, sourceId, title, artist, album, year, coverUrl, artistId, albumId;
        int duration; // secondes, 0 si inconnu

        String key() { return source + ":" + sourceId; }

        /** Format de l'API (tous les champs, meme nuls : le serveur les exige). */
        JSONObject toJson() throws org.json.JSONException {
            JSONObject o = new JSONObject();
            o.put("source", source);
            o.put("source_id", sourceId);
            o.put("title", title == null ? "" : title);
            o.put("artist", artist == null ? "" : artist);
            o.put("album", album == null ? JSONObject.NULL : album);
            o.put("year", year == null ? JSONObject.NULL : year);
            o.put("duration_seconds", duration > 0 ? (Object) duration : JSONObject.NULL);
            o.put("cover_url", coverUrl == null ? JSONObject.NULL : coverUrl);
            o.put("artist_source_id", artistId == null ? JSONObject.NULL : artistId);
            o.put("album_source_id", albumId == null ? JSONObject.NULL : albumId);
            return o;
        }

        static Track from(JSONObject o) {
            Track t = new Track();
            t.source = str(o, "source");
            t.sourceId = str(o, "source_id");
            t.title = str(o, "title");
            t.artist = str(o, "artist");
            t.album = str(o, "album");
            t.year = str(o, "year");
            t.coverUrl = str(o, "cover_url");
            t.artistId = str(o, "artist_source_id");
            t.albumId = str(o, "album_source_id");
            t.duration = o.optInt("duration_seconds", 0);
            return t;
        }

        static List<Track> list(JSONArray a) {
            List<Track> out = new ArrayList<>();
            for (int i = 0; a != null && i < a.length(); i++) out.add(from(a.optJSONObject(i)));
            return out;
        }
    }

    static final class Album {
        String source, sourceId, title, artist, artistId, year, coverUrl;
        int trackCount;
        List<Track> tracks = new ArrayList<>();

        static Album from(JSONObject o) {
            Album a = new Album();
            a.source = str(o, "source");
            a.sourceId = str(o, "source_id");
            a.title = str(o, "title");
            a.artist = str(o, "artist");
            a.artistId = str(o, "artist_source_id");
            a.year = str(o, "year");
            a.coverUrl = str(o, "cover_url");
            a.trackCount = o.optInt("track_count", 0);
            a.tracks = Track.list(o.optJSONArray("tracks"));
            return a;
        }

        static List<Album> list(JSONArray a) {
            List<Album> out = new ArrayList<>();
            for (int i = 0; a != null && i < a.length(); i++) out.add(from(a.optJSONObject(i)));
            return out;
        }
    }

    static final class Artist {
        String source, sourceId, name, pictureUrl;

        static Artist from(JSONObject o) {
            Artist a = new Artist();
            a.source = str(o, "source");
            a.sourceId = str(o, "source_id");
            a.name = str(o, "name");
            a.pictureUrl = str(o, "picture_url");
            return a;
        }

        static List<Artist> list(JSONArray a) {
            List<Artist> out = new ArrayList<>();
            for (int i = 0; a != null && i < a.length(); i++) out.add(from(a.optJSONObject(i)));
            return out;
        }
    }

    /** Ligne de bibliotheque ou d'historique (le serveur ne renvoie que l'essentiel). */
    static final class Entry {
        String kind, source, sourceId, title, subtitle, coverUrl;

        static Entry from(JSONObject o, String defaultKind) {
            Entry e = new Entry();
            e.kind = o.has("kind") ? str(o, "kind") : defaultKind;
            e.source = str(o, "source");
            e.sourceId = str(o, "source_id");
            e.title = str(o, "title");
            e.subtitle = str(o, "subtitle");
            e.coverUrl = str(o, "cover_url");
            return e;
        }

        static List<Entry> list(JSONArray a, String defaultKind) {
            List<Entry> out = new ArrayList<>();
            for (int i = 0; a != null && i < a.length(); i++) out.add(from(a.optJSONObject(i), defaultKind));
            return out;
        }

        /** Une ligne "track" suffit pour lancer la lecture (le flux ne depend que de source/id). */
        Track toTrack() {
            Track t = new Track();
            t.source = source;
            t.sourceId = sourceId;
            t.title = title;
            // historique/bibliotheque : "Artiste - Album" (separateur puce) : on garde l artiste seul
            int cut = subtitle == null ? -1 : subtitle.indexOf(" • ");
            t.artist = cut > 0 ? subtitle.substring(0, cut) : subtitle;
            if (cut > 0) t.album = subtitle.substring(cut + 3);
            t.coverUrl = coverUrl;
            return t;
        }
    }

    static final class Radio {
        String id, title, pictureUrl;
    }

    static final class RadioGroup {
        String title;
        List<Radio> radios = new ArrayList<>();
    }
}
