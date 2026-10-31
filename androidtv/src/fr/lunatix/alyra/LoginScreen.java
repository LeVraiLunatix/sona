package fr.lunatix.alyra;

import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/**
 * Connexion a un compte alyra. par QR code : la TV demande un code au serveur, l'affiche en QR code,
 * puis attend que l'utilisateur l'autorise depuis son telephone (page « connecter un appareil » du site).
 */
final class LoginScreen extends Screen {
    private final LinearLayout body;
    private String deviceCode;
    private int interval = 3;
    private boolean finished;
    private final Runnable pollTask = this::poll;

    LoginScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        page.title("Connexion");
        body = new LinearLayout(a);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setClipChildren(false);
        page.add(body);
        begin();
    }

    @Override View view() { return page.root(); }

    private void begin() {
        finished = false;
        body.removeAllViews();
        body.addView(UI.text(a, "Préparation du QR code…", 18, UI.TEXT3, UI.regular));
        Api.async(() -> Api.deviceStart(Connect.I.name()), this::show, m -> failed(m));
    }

    private void show(JSONObject r) {
        deviceCode = r.optString("device_code");
        interval = Math.max(2, r.optInt("interval", 3));
        String url = r.optString("verify_url");
        String code = r.optString("user_code");
        body.removeAllViews();

        LinearLayout row = new LinearLayout(a);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.addView(new QrView(a, url, 300));

        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(UI.dp(36), 0, 0, 0);
        col.addView(UI.heading(a, "Connecte-toi avec ton téléphone", 28));
        col.addView(step("1", "Scanne ce QR code avec l'appareil photo de ton téléphone."));
        col.addView(step("2", "Connecte-toi à alyra. si on te le demande."));
        col.addView(step("3", "Vérifie que le code est bien celui-ci, puis appuie sur Autoriser :"));
        TextView c = UI.heading(a, code, 40);
        c.setLetterSpacing(0.12f);
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cp.topMargin = UI.dp(14);
        col.addView(c, cp);
        TextView wait = UI.text(a, "En attente de ton autorisation…", 15, UI.TEXT3, UI.regular);
        LinearLayout.LayoutParams wp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        wp.topMargin = UI.dp(18);
        col.addView(wait, wp);
        row.addView(col, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        body.addView(row);

        LinearLayout actions = new LinearLayout(a);
        actions.setPadding(0, UI.dp(22), 0, 0);
        actions.addView(UI.button(a, "Nouveau QR code", false, this::begin));
        actions.addView(UI.button(a, "Annuler", false, a::onBackPressed));
        body.addView(actions);

        a.ensureFocus();
        Api.MAIN.removeCallbacks(pollTask);
        Api.MAIN.postDelayed(pollTask, interval * 1000L);
    }

    private View step(String n, String text) {
        TextView t = UI.text(a, n + "  " + text, 17, UI.TEXT2, UI.regular);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(12);
        t.setLayoutParams(lp);
        return t;
    }

    private void poll() {
        // l'ecran a ete quitte : on arrete d'interroger le serveur
        if (finished || !page.root().isAttachedToWindow()) return;
        final String mine = deviceCode;
        Api.async(() -> Api.devicePoll(mine), r -> {
            if (finished || !mine.equals(deviceCode)) return;
            String status = r.optString("status");
            if ("approved".equals(status)) {
                finished = true;
                Api.save(Api.base, r.optString("session_token"));
                JSONObject acc = r.optJSONObject("account");
                String who = acc == null ? "" : acc.optString("display_name", acc.optString("username"));
                a.toast("Connecté" + (who.isEmpty() ? "" : " : " + who));
                a.onLoggedIn();
            } else if ("gone".equals(status)) {
                failed(r.optString("detail", "Code expiré."));
            } else {
                Api.MAIN.postDelayed(pollTask, interval * 1000L);
            }
        }, m -> {
            // reseau coupe un instant : on reessaie, sans abandonner
            if (!finished && mine.equals(deviceCode)) Api.MAIN.postDelayed(pollTask, interval * 1000L);
        });
    }

    private void failed(String message) {
        finished = true;
        body.removeAllViews();
        TextView t = UI.text(a, message, 18, UI.ERR, UI.regular);
        body.addView(t);
        LinearLayout actions = new LinearLayout(a);
        actions.setPadding(0, UI.dp(18), 0, 0);
        actions.addView(UI.button(a, "Nouveau QR code", true, this::begin));
        body.addView(actions);
        a.ensureFocus();
    }
}
