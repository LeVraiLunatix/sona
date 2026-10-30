package fr.lunatix.alyra;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.Bundle;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;

import fr.lunatix.alyra.Models.Track;

public class MainActivity extends Activity implements Player.Listener {
    private static final String[] TABS = {"Écouter", "Rechercher", "Bibliothèque", "Radios", "Réglages"};
    private static final int RAIL_DP = 210;

    private FrameLayout content;
    private LinearLayout rail;
    private final TextView[] railItems = new TextView[TABS.length];
    private final Screen[] tabScreens = new Screen[TABS.length];
    private final ArrayList<Screen> stack = new ArrayList<>();
    private int tab = -1;
    private NowPlaying now;
    private View mini;
    private ImageView miniCover;
    private TextView miniTitle, miniArtist;
    private IconView miniPlay;
    private FrameLayout root;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Api.init(this);
        UI.init(this);
        Player.I.init(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        root = new FrameLayout(this);
        root.setBackgroundColor(UI.BG);
        setContentView(root);

        LinearLayout h = new LinearLayout(this);
        h.setOrientation(LinearLayout.HORIZONTAL);
        root.addView(h, UI.fill());

        buildRail();
        h.addView(rail, new LinearLayout.LayoutParams(UI.dp(RAIL_DP), ViewGroup.LayoutParams.MATCH_PARENT));
        content = new FrameLayout(this);
        content.setClipChildren(false);
        h.addView(content, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));

        buildMini();
        now = new NowPlaying(this);
        root.addView(now.root, UI.fill());

        if (Api.configured()) Api.async(() -> { Api.loadLiked(); return true; }, ok -> {}, m -> {});
        handle(getIntent(), true);
    }

    @Override protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        handle(i, false);
    }

    /** Extras pratiques pour piloter l'appli en ADB (config, ecran, recherche, capture). */
    private void handle(Intent i, boolean first) {
        String url = i.getStringExtra("url"), tok = i.getStringExtra("token");
        if (url != null || tok != null) {
            Api.save(url != null ? url : Api.base, tok != null ? tok : Api.token);
            tabScreens[0] = null;
            if (Api.configured()) Api.async(() -> { Api.loadLiked(); return true; }, ok -> {}, m -> {});
        }
        String screen = i.getStringExtra("screen");
        int target = !Api.configured() && first ? 4 : 0;
        if (screen != null) {
            switch (screen) {
                case "search": target = 1; break;
                case "library": target = 2; break;
                case "radios": target = 3; break;
                case "settings": target = 4; break;
                default: target = 0;
            }
        }
        if (first || screen != null || url != null) selectTab(target);
        String q = i.getStringExtra("q");
        if (q != null) {
            selectTab(1);
            ((SearchScreen) tabScreens[1]).run(q);
        }
        String open = i.getStringExtra("open"); // test ADB : album:deezer:ID ou artist:deezer:ID
        if (open != null) {
            String[] p = open.split(":");
            if (p.length == 3) {
                if (stack.isEmpty()) selectTab(0);
                push("album".equals(p[0]) ? new AlbumScreen(this, p[1], p[2], false) : new ArtistScreen(this, p[1], p[2]));
            }
        }
        String pq = i.getStringExtra("play"); // test ADB : cherche et joue le premier resultat
        if (pq != null) {
            Api.async(() -> Api.search(pq, null, 0), r -> {
                Player.I.play(r.tracks, 0);
                if (i.getBooleanExtra("now", false)) openNowPlaying();
            }, this::toast);
        } else if (i.getBooleanExtra("now", false)) openNowPlaying();
        if (i.getStringExtra("snap") != null) snapLater(i.getStringExtra("snap"));
    }

    private void snapLater(String name) {
        Api.MAIN.postDelayed(() -> {
            try {
                View v = getWindow().getDecorView();
                Bitmap bm = Bitmap.createBitmap(v.getWidth(), v.getHeight(), Bitmap.Config.ARGB_8888);
                v.draw(new Canvas(bm));
                File tmp = new File(getExternalFilesDir(null), name + ".tmp");
                FileOutputStream fo = new FileOutputStream(tmp);
                bm.compress(Bitmap.CompressFormat.PNG, 100, fo);
                fo.close();
                tmp.renameTo(new File(getExternalFilesDir(null), name + ".png"));
            } catch (Exception ignored) {}
        }, 4000);
    }

    // ---- rail -------------------------------------------------------------

    private void buildRail() {
        rail = new LinearLayout(this);
        rail.setOrientation(LinearLayout.VERTICAL);
        rail.setBackgroundColor(0xFF0E0D0E);
        rail.setPadding(UI.dp(14), UI.dp(34), UI.dp(14), UI.dp(20));
        TextView logo = UI.text(this, "Alyra", 34, UI.TEXT, UI.semibold);
        logo.setPadding(UI.dp(14), 0, 0, UI.dp(30));
        rail.addView(logo);
        for (int i = 0; i < TABS.length; i++) {
            final int idx = i;
            TextView t = UI.text(this, TABS[i], 19, UI.SOFT, UI.regular);
            t.setPadding(UI.dp(16), UI.dp(12), UI.dp(12), UI.dp(12));
            UI.focusable(t, 12, true, 1.0f);
            t.setOnClickListener(v -> selectTab(idx));
            // ouvrir un onglet des qu'il prend le focus serait trop nerveux : on attend OK
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.bottomMargin = UI.dp(4);
            rail.addView(t, lp);
            railItems[i] = t;
        }
    }

    int contentWidthDp() {
        return Math.round(getResources().getDisplayMetrics().widthPixels / UI.density) - RAIL_DP;
    }

    void selectTab(int i) {
        stack.clear();
        tab = i;
        if (tabScreens[i] == null) {
            switch (i) {
                case 0: tabScreens[i] = new HomeScreen(this); break;
                case 1: tabScreens[i] = new SearchScreen(this); break;
                case 2: tabScreens[i] = new LibraryScreen(this); break;
                case 3: tabScreens[i] = new RadiosScreen(this); break;
                default: tabScreens[i] = new SettingsScreen(this);
            }
        } else if (i == 0 || i == 2) {
            tabScreens[i] = i == 0 ? new HomeScreen(this) : new LibraryScreen(this); // donnees fraiches
        }
        stack.add(tabScreens[i]);
        for (int k = 0; k < railItems.length; k++)
            railItems[k].setTextColor(k == i ? UI.CYAN : UI.SOFT);
        display();
    }

    void push(Screen s) {
        stack.add(s);
        display();
    }

    private void display() {
        content.removeAllViews();
        Screen top = stack.get(stack.size() - 1);
        View v = top.view();
        if (v.getParent() != null) ((ViewGroup) v.getParent()).removeView(v);
        content.addView(v, UI.fill());
        content.addView(mini);
        updateMini();
        top.onShow();
        Api.MAIN.post(content::requestFocus); // le focus passe du rail au contenu
    }

    /** Donne le focus au contenu s'il n'est nulle part (apres un chargement, un changement d'ecran). */
    void ensureFocus() {
        View f = getCurrentFocus();
        if (f == null || !f.isShown()) {
            if (content.getChildCount() > 0) content.getChildAt(0).requestFocus();
        }
    }

    // ---- mini-lecteur -----------------------------------------------------

    private void buildMini() {
        LinearLayout m = new LinearLayout(this);
        m.setOrientation(LinearLayout.HORIZONTAL);
        m.setGravity(Gravity.CENTER_VERTICAL);
        m.setPadding(UI.dp(14), UI.dp(8), UI.dp(14), UI.dp(8));
        UI.focusable(m, 18, true, 1.02f);
        m.setBackground(miniBg());
        miniCover = UI.cover(this, 52, 8);
        m.addView(miniCover);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        miniTitle = UI.oneLine(UI.text(this, "", 17, UI.TEXT, UI.semibold));
        miniArtist = UI.oneLine(UI.text(this, "", 14, UI.MUTED, UI.regular));
        col.addView(miniTitle);
        col.addView(miniArtist);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        cp.leftMargin = UI.dp(14);
        m.addView(col, cp);
        miniPlay = new IconView(this, IconView.PLAY, 46, true);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(UI.dp(46), UI.dp(46));
        ip.leftMargin = UI.dp(12);
        miniPlay.setOnClickListener(v -> Player.I.toggle());
        m.addView(miniPlay, ip);
        m.setOnClickListener(v -> openNowPlaying());
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(UI.dp(640), UI.dp(70), Gravity.BOTTOM | Gravity.START);
        lp.leftMargin = UI.dp(40);
        lp.bottomMargin = UI.dp(20);
        m.setLayoutParams(lp);
        m.setVisibility(View.GONE);
        mini = m;
    }

    private android.graphics.drawable.Drawable miniBg() {
        android.graphics.drawable.StateListDrawable sl = new android.graphics.drawable.StateListDrawable();
        sl.addState(new int[]{android.R.attr.state_focused}, UI.shape(0xFF2F3A3E, UI.CYAN, UI.dp(2), 18));
        sl.addState(new int[]{}, UI.shape(0xF0242325, 0, 0, 18));
        return sl;
    }

    private String miniKey;

    private void updateMini() {
        Track t = Player.I.current();
        if (t == null || Player.I.state() == Player.IDLE) {
            mini.setVisibility(View.GONE);
            return;
        }
        mini.setVisibility(View.VISIBLE);
        if (!t.key().equals(miniKey)) {
            miniKey = t.key();
            miniTitle.setText(t.title);
            miniArtist.setText(t.artist == null ? "" : t.artist);
            Img.load(miniCover, t.coverUrl, UI.dp(52));
        }
        int st = Player.I.state();
        miniPlay.setType(st == Player.PLAYING ? IconView.PAUSE : st == Player.LOADING ? IconView.LOADING : IconView.PLAY);
    }

    @Override public void onChange() { updateMini(); }

    @Override protected void onStart() {
        super.onStart();
        Player.I.addListener(this);
        updateMini();
    }

    @Override protected void onStop() {
        Player.I.removeListener(this);
        super.onStop();
    }

    // ---- lecteur plein ecran ----------------------------------------------

    void openNowPlaying() {
        if (Player.I.current() != null) now.open();
    }

    void closeNowPlaying() {
        if (now.isOpen()) {
            now.close();
            ensureFocus();
        }
    }

    // ---- divers -----------------------------------------------------------

    void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_SHORT).show(); }

    void hideKeyboard(View v) {
        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(v.getWindowToken(), 0);
    }

    /** Sur TV le clavier ne doit s'ouvrir que sur OK, sinon il avale les fleches du D-pad. */
    void keyboardOnClick(android.widget.EditText e) {
        e.setShowSoftInputOnFocus(false);
        e.setOnClickListener(v -> {
            InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
            if (imm != null) imm.showSoftInput(e, 0);
        });
    }

    @Override public boolean onKeyDown(int code, KeyEvent e) {
        switch (code) {
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
            case KeyEvent.KEYCODE_HEADSETHOOK:
                Player.I.toggle();
                return true;
            case KeyEvent.KEYCODE_MEDIA_PLAY:
                if (!Player.I.isPlaying()) Player.I.toggle();
                return true;
            case KeyEvent.KEYCODE_MEDIA_PAUSE:
                Player.I.pause();
                return true;
            case KeyEvent.KEYCODE_MEDIA_NEXT:
                Player.I.next();
                return true;
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                Player.I.previous();
                return true;
            case KeyEvent.KEYCODE_MEDIA_FAST_FORWARD:
                Player.I.seekBy(15000);
                return true;
            case KeyEvent.KEYCODE_MEDIA_REWIND:
                Player.I.seekBy(-15000);
                return true;
            default:
                return super.onKeyDown(code, e);
        }
    }

    @Override public void onBackPressed() {
        if (now.isOpen()) { closeNowPlaying(); return; }
        if (stack.size() > 1) {
            stack.remove(stack.size() - 1);
            display();
            return;
        }
        if (tab > 0) { selectTab(0); return; }
        moveTaskToBack(true); // la musique continue
    }
}
