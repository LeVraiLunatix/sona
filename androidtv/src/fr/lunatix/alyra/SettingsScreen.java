package fr.lunatix.alyra;

import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

final class SettingsScreen extends Screen {
    private final EditText url, token;
    private final TextView status;
    private final TextView account;

    SettingsScreen(MainActivity a) {
        super(a);
        page = new Page(a);
        page.title("Réglages");
        page.section("Compte alyra.");
        account = UI.text(a, Api.configured() ? "Vérification du compte…" : "Pas connecté.", 17, UI.TEXT2, UI.regular);
        page.add(account);
        LinearLayout acts = page.actions();
        acts.addView(UI.button(a, "Se connecter avec un QR code", !Api.configured(), () -> a.push(new LoginScreen(a))));
        acts.addView(UI.button(a, "Se déconnecter", false, this::signOut));
        if (Api.configured()) {
            Api.async(Api::me, me -> account.setText("Connecté : " + me.optString("display_name", me.optString("username"))
                    + " (" + me.optString("username") + ")"), m -> account.setText(m));
        }
        page.section("Serveur (avancé)");
        page.note("Adresse de l'API et jeton : seulement si tu n'utilises pas le QR code (jeton du serveur).");
        url = field(Api.DEFAULT_URL, Api.base, false);
        token = field("Jeton API", Api.token, true);
        status = UI.text(a, "", 16, UI.TEXT3, UI.regular);
        LinearLayout actions = page.actions();
        actions.addView(UI.button(a, "Enregistrer et tester", true, this::saveAndTest));
        page.add(status);
        page.section("À propos");
        page.note("Alyra pour Android TV — lit ta musique Sona. Dans le lecteur : gauche/droite sur la barre = ±10 s, touches média prises en charge.");
    }

    private EditText field(String hint, String value, boolean secret) {
        EditText e = new EditText(a);
        e.setHint(hint);
        e.setHintTextColor(UI.TEXT3);
        e.setText(value);
        e.setTextColor(UI.TEXT);
        e.setTextSize(18);
        e.setTypeface(UI.regular);
        e.setSingleLine(true);
        e.setImeOptions(EditorInfo.IME_ACTION_DONE);
        e.setInputType(secret
                ? InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        e.setPadding(UI.dp(18), UI.dp(12), UI.dp(18), UI.dp(12));
        e.setBackground(UI.shape(UI.RAISED, 0, 0, 12));
        e.setOnFocusChangeListener((v, has) ->
                v.setBackground(has ? UI.shape(UI.FILL_FOCUS, UI.ACCENT, UI.dp(2), 12) : UI.shape(UI.RAISED, 0, 0, 12)));
        a.keyboardOnClick(e);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(UI.dp(560), ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = UI.dp(10);
        page.col.addView(e, lp);
        return e;
    }

    private void done() {
        Api.save(Api.base, "");
        a.toast("Déconnecté");
        a.onLoggedOut();
    }

    private void signOut() {
        if (!Api.configured()) { a.toast("Déjà déconnecté"); return; }
        // le serveur révoque d'abord la session de la TV (il lui faut encore le jeton), puis on l'oublie ici
        Api.async(() -> { Api.send("POST", "/auth/logout", null); return true; }, ok -> done(), m -> done());
    }

    private void saveAndTest() {
        Api.save(url.getText().toString(), token.getText().toString());
        status.setTextColor(UI.TEXT3);
        status.setText("Test en cours…");
        Api.async(() -> {
            Api.get("/health");
            JSONObject s = new JSONObject(Api.get("/settings")); // exige le jeton
            return s.optString("quality", "?");
        }, q -> {
            status.setTextColor(UI.ACCENT);
            status.setText("Connecté — qualité " + q + ". Enregistré.");
            Api.async(() -> { Api.loadLiked(); return true; }, ok -> {}, m -> {});
        }, msg -> {
            status.setTextColor(UI.ERR);
            status.setText("Échec : " + msg);
        });
    }

    @Override View view() { return page.root(); }
}
