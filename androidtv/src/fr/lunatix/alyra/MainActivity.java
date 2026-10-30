package fr.lunatix.alyra;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
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
    private static final String[] TABS = {"Accueil", "Recherche", "Bibliothèque", "Radios", "Réglages"};
    private static final int[] TAB_ICONS = {IconView.HOME, IconView.SEARCH, IconView.LIBRARY, IconView.RADIO, IconView.SETTINGS};
    private static final int SIDE_DP = 230;

    private FrameLayout content;
    private LinearLayout side;
    private final View[] navItems = new View[TABS.length];
    private final IconView[] navIcons = new IconView[TABS.length];
    private final TextView[] navLabels = new TextView[TABS.length];
    private final Screen[] tabScreens = new Screen[TABS.length];
    private final ArrayList<Screen> stack = new ArrayList<>();
    private int tab = -1;
    private NowPlaying now;
    private View bar;
    private ImageView barCover;
    private TextView barTitle, barArtist;
    private IconView barPlay, barHeart, barPrev, barNext;
    private BarProgress barProgress;
    private FrameLayout root;

    /** Filet de progression tout fin en haut de la barre de lecture. */
    static final class BarProgress extends View {
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        BarProgress(Context c) { super(c); }
        @Override protected void onDraw(Canvas c) {
            int dur = Player.I.duration();
            float f = dur > 0 ? Math.min(1f, Player.I.position() / (float) dur) : 0f;
            p.setColor(UI.FILL_STRONG);
            c.drawRect(0, 0, getWidth(), getHeight(), p);
            p.setColor(UI.ACCENT);
            c.drawRect(0, 0, getWidth() * f, getHeight(), p);
        }
    }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Api.init(this);
        UI.init(this);
        Player.I.init(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        root = new FrameLayout(this);
        root.setBackgroundColor(UI.BG);
        root.addView(new Brand.Background(this), UI.fill());
        setContentView(root);

        LinearLayout h = new LinearLayout(this);
        h.setOrientation(LinearLayout.HORIZONTAL);
        root.addView(h, UI.fill());

        buildSide();
        h.addView(side, new LinearLayout.LayoutParams(UI.dp(SIDE_DP), ViewGroup.LayoutParams.MATCH_PARENT));
        content = new FrameLayout(this);
        content.setClipChildren(false);
        h.addView(content, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));

        buildBar();
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

    // ---- menu lateral -----------------------------------------------------

    private void buildSide() {
        side = new LinearLayout(this);
        side.setOrientation(LinearLayout.VERTICAL);
        side.setBackground(UI.shape(0x0DFFFFFF, 0, 0, 0));
        side.setPadding(UI.dp(18), UI.dp(34), UI.dp(14), UI.dp(20));
        View logo = Brand.lockup(this, 34, 26);
        LinearLayout.LayoutParams lg = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lg.leftMargin = UI.dp(4);
        lg.bottomMargin = UI.dp(34);
        side.addView(logo, lg);
        for (int i = 0; i < TABS.length; i++) {
            final int idx = i;
            LinearLayout item = new LinearLayout(this);
            item.setGravity(Gravity.CENTER_VERTICAL);
            item.setPadding(UI.dp(14), UI.dp(11), UI.dp(12), UI.dp(11));
            UI.focusable(item, 14, true, 1.0f);
            IconView ic = new IconView(this, TAB_ICONS[i], 26, UI.TEXT2);
            item.addView(ic, new LinearLayout.LayoutParams(UI.dp(26), UI.dp(26)));
            TextView t = UI.text(this, TABS[i], 18, UI.TEXT2, UI.semibold);
            LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            tp.leftMargin = UI.dp(14);
            item.addView(t, tp);
            item.setOnClickListener(v -> selectTab(idx));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.bottomMargin = UI.dp(4);
            side.addView(item, lp);
            navItems[i] = item;
            navIcons[i] = ic;
            navLabels[i] = t;
        }
    }

    int contentWidthDp() {
        return Math.round(getResources().getDisplayMetrics().widthPixels / UI.density) - SIDE_DP;
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
        for (int k = 0; k < navItems.length; k++) {
            boolean on = k == i;
            navLabels[k].setTextColor(on ? UI.TEXT : UI.TEXT2);
            navIcons[k].setTint(on ? UI.TEXT : UI.TEXT2);
            // l'onglet actif garde une plaque de verre meme sans focus
            ((LinearLayout) navItems[k]).setForeground(on ? UI.shape(UI.FILL_STRONG, 0, 0, 14) : null);
        }
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
        content.addView(bar);
        updateBar();
        top.onShow();
        Api.MAIN.post(content::requestFocus); // le focus passe du menu au contenu
    }

    /** Donne le focus au contenu s'il n'est nulle part (apres un chargement, un changement d'ecran). */
    void ensureFocus() {
        View f = getCurrentFocus();
        if (f == null || !f.isShown()) {
            if (content.getChildCount() > 0) content.getChildAt(0).requestFocus();
        }
    }

    // ---- barre de lecture -------------------------------------------------

    private void buildBar() {
        LinearLayout b = new LinearLayout(this);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setBackground(UI.shape(UI.GLASS, UI.HAIR, UI.dp(1), 22));
        b.setClipToOutline(true);
        b.setOutlineProvider(new UI.RoundOutline(UI.dp(22)));

        barProgress = new BarProgress(this);
        b.addView(barProgress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, UI.dp(3)));

        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(UI.dp(10), UI.dp(8), UI.dp(14), UI.dp(8));
        b.addView(row, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // gauche : pochette + titre (ouvre le lecteur plein ecran)
        LinearLayout left = new LinearLayout(this);
        left.setGravity(Gravity.CENTER_VERTICAL);
        left.setPadding(UI.dp(4), UI.dp(4), UI.dp(8), UI.dp(4));
        UI.focusable(left, 16, true, 1.0f);
        barCover = UI.cover(this, 54, 12);
        left.addView(barCover);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        barTitle = UI.oneLine(UI.text(this, "", 17, UI.TEXT, UI.semibold));
        barArtist = UI.oneLine(UI.text(this, "", 14, UI.TEXT3, UI.regular));
        col.addView(barTitle);
        col.addView(barArtist);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        cp.leftMargin = UI.dp(14);
        left.addView(col, cp);
        left.setOnClickListener(v -> openNowPlaying());
        row.addView(left, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        barPrev = barButton(row, IconView.PREV, 44, false);
        barPlay = barButton(row, IconView.PLAY, 52, true);
        barNext = barButton(row, IconView.NEXT, 44, false);
        barHeart = barButton(row, IconView.HEART, 44, false);
        barPrev.setOnClickListener(v -> Player.I.previous());
        barPlay.setOnClickListener(v -> Player.I.toggle());
        barNext.setOnClickListener(v -> Player.I.next());
        barHeart.setOnClickListener(v -> toggleLike());

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM);
        lp.leftMargin = UI.dp(36);
        lp.rightMargin = UI.dp(36);
        lp.bottomMargin = UI.dp(18);
        b.setLayoutParams(lp);
        b.setVisibility(View.GONE);
        bar = b;
    }

    private IconView barButton(LinearLayout row, int type, int sizeDp, boolean accent) {
        IconView v = new IconView(this, type, sizeDp, accent);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(UI.dp(sizeDp), UI.dp(sizeDp));
        lp.leftMargin = UI.dp(10);
        row.addView(v, lp);
        return v;
    }

    private void toggleLike() {
        Track t = Player.I.current();
        if (t == null) return;
        boolean like = !Api.isLiked(t.key());
        barHeart.setType(like ? IconView.HEART_ON : IconView.HEART);
        Api.async(() -> { Api.setLiked(t, like); return true; }, ok -> {}, m -> {
            toast(m);
            updateBar();
        });
    }

    private String barKey;

    private void updateBar() {
        Track t = Player.I.current();
        if (t == null || Player.I.state() == Player.IDLE) {
            bar.setVisibility(View.GONE);
            return;
        }
        bar.setVisibility(View.VISIBLE);
        if (!t.key().equals(barKey)) {
            barKey = t.key();
            barTitle.setText(t.title);
            barArtist.setText(t.artist == null ? "" : t.artist);
            Img.load(barCover, t.coverUrl, UI.dp(54));
        }
        int st = Player.I.state();
        barPlay.setType(st == Player.PLAYING ? IconView.PAUSE : st == Player.LOADING ? IconView.LOADING : IconView.PLAY);
        barHeart.setType(Api.isLiked(t.key()) ? IconView.HEART_ON : IconView.HEART);
        barPrev.setAlpha(Player.I.hasPrevious() ? 1f : .4f);
        barNext.setAlpha(Player.I.hasNext() ? 1f : .4f);
        barProgress.invalidate();
    }

    @Override public void onChange() { updateBar(); }

    @Override protected void onStart() {
        super.onStart();
        Player.I.addListener(this);
        updateBar();
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
