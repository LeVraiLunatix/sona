//! Tests HTTP du service (routeur complet + vraie base) : authentification,
//! bannissement immédiat, administration, compte, hook, routes internes.

mod common;
use axum::http::StatusCode;
use common::{token_for, Api};
use serde_json::json;
use uuid::Uuid;

async fn staff(api: &Api, name: &str, role: &str) -> (Uuid, String) {
    let id = api.db.named(name).await;
    api.db.make_role(id, role).await;
    (id, api.token(id))
}

#[tokio::test]
async fn requests_without_a_valid_token_are_refused() {
    let Some(api) = Api::new().await else { return };
    let u = api.db.named("alice").await;
    assert_eq!(api.call("GET", "/me", None, None).await.0, StatusCode::UNAUTHORIZED);
    assert_eq!(api.call("GET", "/me", Some("n'importe quoi"), None).await.0, StatusCode::UNAUTHORIZED);
    // Jeton signé avec un autre secret.
    let forged = token_for("un-autre-secret-un-autre-secret-123", u, json!({}));
    assert_eq!(api.call("GET", "/me", Some(&forged), None).await.0, StatusCode::UNAUTHORIZED);
    // Clés anon / service_role de Supabase : refusées.
    for role in ["anon", "service_role"] {
        let t = token_for(api.state.cfg.jwt_secret.as_deref().unwrap(), u, json!({ "role": role }));
        assert_eq!(api.call("GET", "/me", Some(&t), None).await.0, StatusCode::UNAUTHORIZED, "{role}");
    }
    // Utilisateur inexistant.
    assert_eq!(api.call("GET", "/me", Some(&api.token(Uuid::new_v4())), None).await.0, StatusCode::UNAUTHORIZED);
    let (st, body) = api.call("GET", "/me", Some(&api.token(u)), None).await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(body["username"], "alice");
    assert_eq!(body["staff"], false);
}

#[tokio::test]
async fn a_forged_role_in_the_token_changes_nothing() {
    let Some(api) = Api::new().await else { return };
    let u = api.db.named("mallory").await;
    let t = token_for(api.state.cfg.jwt_secret.as_deref().unwrap(), u, json!({ "app_metadata": { "role": "admin" }, "user_role": "admin", "user_metadata": { "role": "admin" } }));
    let (_, me) = api.call("GET", "/me", Some(&t), None).await;
    assert_eq!(me["role"], "user");
    let (st, _) = api.call("POST", "/admin/sanction", Some(&t), Some(json!({ "target": u, "kind": "warning", "reason": "test" }))).await;
    assert_eq!(st, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn a_user_without_the_admin_role_cannot_call_any_admin_action() {
    let Some(api) = Api::new().await else { return };
    let user = api.db.named("quidam").await;
    let target = api.db.named("cible").await;
    let t = api.token(user);
    let x = Uuid::new_v4();
    let calls = [
        ("/admin/sanction", json!({ "target": target, "kind": "ban", "reason": "motif valable" })),
        ("/admin/lift", json!({ "target": target, "reason": "motif valable" })),
        ("/admin/reset-profile", json!({ "target": target, "fields": ["bio"], "reason": "motif valable" })),
        ("/admin/role", json!({ "target": user, "role": "admin", "reason": "motif valable" })),
        ("/admin/revoke-sessions", json!({ "target": target, "reason": "motif valable" })),
        ("/admin/ban-identifier", json!({ "kind": "email_domain", "value": "x.test", "reason": "motif valable" })),
        ("/admin/forbidden-term", json!({ "term": "motbizarre", "kind": "offensive" })),
        ("/admin/report", json!({ "report": x, "status": "resolved" })),
        ("/admin/appeal", json!({ "appeal": x, "accept": true, "response": "ok pour moi" })),
        ("/admin/delete-user", json!({ "target": target, "reason": "motif valable" })),
        ("/admin/content", json!({ "action": "delete", "kind": "playlist", "owner": target, "ref": "12", "reason": "motif valable" })),
        ("/admin/session", json!({ "code": "ABCD", "action": "close", "reason": "motif valable" })),
    ];
    for (path, body) in &calls {
        assert_eq!(api.call("POST", path, Some(&t), Some(body.clone())).await.0, StatusCode::FORBIDDEN, "{path} (utilisateur)");
        assert_eq!(api.call("POST", path, None, Some(body.clone())).await.0, StatusCode::UNAUTHORIZED, "{path} (anonyme)");
    }
    // Rien n'a bougé.
    assert_eq!(api.db.su_scalar("select count(*) from public.sanctions").await, "0");
    assert_eq!(api.db.su_scalar("select count(*) from public.audit_log").await, "0");
    assert_eq!(api.db.su_scalar(&format!("select role from public.profiles where id = '{user}'")).await, "user");
}

#[tokio::test]
async fn a_moderator_has_limited_powers_over_http() {
    let Some(api) = Api::new().await else { return };
    let (_, modo) = staff(&api, "modo", "moderator").await;
    let target = api.db.named("cible").await;
    let ok = api.call("POST", "/admin/sanction", Some(&modo), Some(json!({ "target": target, "kind": "warning", "reason": "langage déplacé" }))).await;
    assert_eq!(ok.0, StatusCode::OK);
    assert_eq!(ok.1["warnings"], 1);
    // Pas de ban, pas de suspension > 7 jours, pas de rôle, pas de suppression, pas d'IP.
    let ban = api.call("POST", "/admin/sanction", Some(&modo), Some(json!({ "target": target, "kind": "ban", "reason": "motif valable" }))).await;
    assert_eq!(ban.0, StatusCode::FORBIDDEN);
    let long = api.call("POST", "/admin/sanction", Some(&modo), Some(json!({ "target": target, "kind": "suspension", "reason": "motif valable", "duration_seconds": 30 * 86400 }))).await;
    assert_eq!(long.0, StatusCode::FORBIDDEN);
    for (path, body) in [
        ("/admin/role", json!({ "target": target, "role": "moderator", "reason": "motif valable" })),
        ("/admin/delete-user", json!({ "target": target, "reason": "motif valable" })),
        ("/admin/ban-identifier", json!({ "kind": "ip", "value": "10.0.0.1", "reason": "motif valable" })),
        ("/admin/forbidden-term", json!({ "term": "motbizarre", "kind": "offensive" })),
    ] {
        assert_eq!(api.call("POST", path, Some(&modo), Some(body)).await.0, StatusCode::FORBIDDEN, "{path}");
    }
    // Motif obligatoire.
    let nomotive = api.call("POST", "/admin/sanction", Some(&modo), Some(json!({ "target": target, "kind": "warning", "reason": "" }))).await;
    assert_eq!(nomotive.0, StatusCode::BAD_REQUEST);
    assert!(nomotive.1["message"].as_str().unwrap().contains("motif"));
    // Type inconnu / identifiants mal formés.
    assert_eq!(api.call("POST", "/admin/sanction", Some(&modo), Some(json!({ "target": target, "kind": "explose", "reason": "motif valable" }))).await.0, StatusCode::BAD_REQUEST);
    assert_eq!(api.call("POST", "/admin/sanction", Some(&modo), Some(json!({ "target": "pas-un-uuid", "kind": "warning", "reason": "x" }))).await.0.is_client_error(), true);
}

#[tokio::test]
async fn a_ban_applies_immediately_to_an_open_session_and_can_be_lifted() {
    let Some(api) = Api::new().await else { return };
    let (_, admin) = staff(&api, "boss", "admin").await;
    let victim = api.db.named("troll").await;
    let vt = api.token(victim);
    assert_eq!(api.call("GET", "/me", Some(&vt), None).await.0, StatusCode::OK);
    api.db.su(&format!("insert into auth.sessions (user_id) values ('{victim}')")).await;

    let r = api.call("POST", "/admin/sanction", Some(&admin), Some(json!({ "target": victim, "kind": "ban", "reason": "harcèlement répété" }))).await;
    assert_eq!(r.0, StatusCode::OK, "{:?}", r.1);

    // Même jeton, encore valable une heure : refusé tout de suite, avec la raison.
    let (st, body) = api.call("GET", "/me", Some(&vt), None).await;
    assert_eq!(st, StatusCode::FORBIDDEN);
    assert_eq!(body["error"], "sanctioned");
    assert_eq!(body["status"], "banned");
    assert_eq!(body["reason"], "harcèlement répété");
    // Auth ne renouvellera plus son jeton, et ses sessions sont fermées.
    assert_eq!(api.db.su_scalar(&format!("select banned_until::date from auth.users where id = '{victim}'")).await, "2999-12-31");
    assert_eq!(api.db.su_scalar(&format!("select count(*) from auth.sessions where user_id = '{victim}'")).await, "0");
    // Les actions réservées aux comptes en règle sont refusées…
    assert_eq!(api.call("POST", "/lastfm/start", Some(&vt), Some(json!({ "return_to": "https://trysona.fr/" }))).await.0, StatusCode::FORBIDDEN);
    // …mais ses droits RGPD restent : export, suppression, déconnexion de Last.fm.
    assert_eq!(api.call("GET", "/account/export", Some(&vt), None).await.0, StatusCode::OK);
    assert_eq!(api.call("DELETE", "/lastfm", Some(&vt), None).await.0, StatusCode::OK);
    // Le serveur musique, lui aussi, le voit tout de suite.
    let (st, v) = api.internal("POST", "/internal/verify", Some(json!({ "token": vt }))).await;
    assert_eq!(st, StatusCode::FORBIDDEN);
    assert_eq!(v["error"], "sanctioned");

    // Levée du ban : de nouveau accepté sans reconnexion.
    let l = api.call("POST", "/admin/lift", Some(&admin), Some(json!({ "target": victim, "reason": "appel accepté" }))).await;
    assert_eq!(l.0, StatusCode::OK);
    assert_eq!(api.call("GET", "/me", Some(&vt), None).await.0, StatusCode::OK);
    assert_eq!(api.db.su_scalar(&format!("select banned_until is null from auth.users where id = '{victim}'")).await, "true");
}

#[tokio::test]
async fn a_suspension_sets_the_end_date_and_expires() {
    let Some(api) = Api::new().await else { return };
    let (_, admin) = staff(&api, "boss", "admin").await;
    let u = api.db.named("agite").await;
    let r = api.call("POST", "/admin/sanction", Some(&admin), Some(json!({ "target": u, "kind": "suspension", "reason": "une heure de calme", "duration_seconds": 3600 }))).await;
    assert_eq!(r.0, StatusCode::OK);
    let (st, b) = api.call("GET", "/me", Some(&api.token(u)), None).await;
    assert_eq!((st, b["status"].as_str()), (StatusCode::FORBIDDEN, Some("suspended")));
    assert!(b["until"].is_string());
    api.db.su(&format!("update public.profiles set status_until = now() - interval '1 minute' where id = '{u}'")).await;
    assert_eq!(api.call("GET", "/me", Some(&api.token(u)), None).await.0, StatusCode::OK);
}

#[tokio::test]
async fn demoting_or_promoting_takes_effect_on_the_next_request() {
    let Some(api) = Api::new().await else { return };
    let (_, admin) = staff(&api, "boss", "admin").await;
    let (modo_id, modo) = staff(&api, "modo", "moderator").await;
    let t = api.db.named("cible").await;
    let body = json!({ "target": t, "kind": "warning", "reason": "motif valable" });
    assert_eq!(api.call("POST", "/admin/sanction", Some(&modo), Some(body.clone())).await.0, StatusCode::OK);
    let r = api.call("POST", "/admin/role", Some(&admin), Some(json!({ "target": modo_id, "role": "user", "reason": "fin de mission" }))).await;
    assert_eq!(r.0, StatusCode::OK);
    assert_eq!(api.call("POST", "/admin/sanction", Some(&modo), Some(body)).await.0, StatusCode::FORBIDDEN);
    assert_eq!(api.call("GET", "/me", Some(&modo), None).await.1["staff"], false);
}

#[tokio::test]
async fn account_export_and_deletion() {
    let Some(api) = Api::new().await else { return };
    let (_, admin) = staff(&api, "boss", "admin").await;
    let u = api.db.named("partante").await;
    let other = api.db.named("amie").await;
    api.db.friends(u, other).await;
    let t = api.token(u);
    // Un avertissement n'empêche rien.
    api.call("POST", "/admin/sanction", Some(&admin), Some(json!({ "target": u, "kind": "warning", "reason": "langage déplacé" }))).await;
    let (st, ex) = api.call("GET", "/account/export", Some(&t), None).await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(ex["account"]["profile"]["username"], "partante");
    assert_eq!(ex["account"]["friendships"].as_array().unwrap().len(), 1);
    assert_eq!(ex["account"]["sanctions"].as_array().unwrap().len(), 1);
    // Confirmation obligatoire.
    for bad in ["", "oui", "supprimer mon compte"] {
        assert_eq!(api.call("DELETE", "/account", Some(&t), Some(json!({ "confirm": bad }))).await.0, StatusCode::BAD_REQUEST, "{bad:?}");
    }
    assert_eq!(api.db.su_scalar("select count(*) from auth.users").await, "3");
    let (st, _) = api.call("DELETE", "/account", Some(&t), Some(json!({ "confirm": "SUPPRIMER MON COMPTE" }))).await;
    assert_eq!(st, StatusCode::OK);
    // Tout a disparu (cascade) : compte, profil, réglages, amitiés, sanctions.
    for table in ["auth.users where id", "public.profiles where id", "public.user_settings where user_id", "public.privacy_settings where user_id", "public.sanctions where user_id"] {
        assert_eq!(api.db.su_scalar(&format!("select count(*) from {table} = '{u}'")).await, "0", "{table}");
    }
    assert_eq!(api.db.su_scalar(&format!("select count(*) from public.friendships where '{u}' in (requester_id, addressee_id)")).await, "0");
    // Le journal garde la trace (obligation de traçabilité, durée de rétention définie).
    assert_eq!(api.db.su_scalar("select count(*) from public.audit_log where action = 'account.delete_self'").await, "1");
    // Le jeton, lui, ne vaut plus rien.
    assert_eq!(api.call("GET", "/me", Some(&t), None).await.0, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn an_admin_deletes_an_account_but_never_another_admin_or_themselves() {
    let Some(api) = Api::new().await else { return };
    let (admin_id, admin) = staff(&api, "boss", "admin").await;
    let (admin2, _) = staff(&api, "boss2", "admin").await;
    let u = api.db.named("fautif").await;
    for t in [admin_id, admin2] {
        let (st, _) = api.call("POST", "/admin/delete-user", Some(&admin), Some(json!({ "target": t, "reason": "motif valable" }))).await;
        assert_eq!(st, StatusCode::FORBIDDEN);
    }
    assert_eq!(api.call("POST", "/admin/delete-user", Some(&admin), Some(json!({ "target": u, "reason": "" }))).await.0, StatusCode::BAD_REQUEST);
    assert_eq!(api.db.su_scalar(&format!("select count(*) from auth.users where id = '{u}'")).await, "1");
    let (st, _) = api.call("POST", "/admin/delete-user", Some(&admin), Some(json!({ "target": u, "reason": "demande RGPD par e-mail" }))).await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(api.db.su_scalar(&format!("select count(*) from auth.users where id = '{u}'")).await, "0");
    assert_eq!(api.db.su_scalar("select count(*) from public.audit_log where action = 'account.delete'").await, "1");
}

#[tokio::test]
async fn the_signup_hook_checks_the_signature_and_blocks_abuse() {
    let Some(api) = Api::new().await else { return };
    let secret = api.state.cfg.hook_secret.clone().unwrap();
    let body = json!({ "metadata": { "ip_address": "203.0.113.9" }, "user": { "email": "x@mailinator.com", "app_metadata": { "provider": "email" } } }).to_string();
    let ts = chrono::Utc::now().timestamp();
    let sig = sona_accounts::webhook::sign(&secret, "msg_1", ts, body.as_bytes()).unwrap();
    let hdrs = |sig: &str| vec![("webhook-id", "msg_1".to_string()), ("webhook-timestamp", ts.to_string()), ("webhook-signature", sig.to_string()), ("content-type", "application/json".to_string())];
    // Mauvaise signature, ou aucune : refusé.
    assert_eq!(api.call_raw("POST", "/hooks/before-user-created", &hdrs("v1,AAAA"), body.clone()).await.0, StatusCode::UNAUTHORIZED);
    assert_eq!(api.call_raw("POST", "/hooks/before-user-created", &[], body.clone()).await.0, StatusCode::UNAUTHORIZED);
    // Signature valable mais corps modifié : refusé.
    assert_eq!(api.call_raw("POST", "/hooks/before-user-created", &hdrs(&sig), format!(" {body}")).await.0, StatusCode::UNAUTHORIZED);
    let (st, out) = api.call_raw("POST", "/hooks/before-user-created", &hdrs(&sig), body.clone()).await;
    assert_eq!(st, StatusCode::FORBIDDEN, "{out}");
    assert_eq!(out["error"]["http_code"], 403);
    assert!(out["error"]["message"].as_str().unwrap().contains("temporaires"));
    // Une adresse normale passe.
    let ok_body = json!({ "metadata": { "ip_address": "203.0.113.10" }, "user": { "email": "vrai@example.org", "app_metadata": { "provider": "email" } } }).to_string();
    let ok_sig = sona_accounts::webhook::sign(&secret, "msg_1", ts, ok_body.as_bytes()).unwrap();
    let (st, out) = api.call_raw("POST", "/hooks/before-user-created", &hdrs(&ok_sig), ok_body).await;
    assert_eq!((st, out), (StatusCode::OK, json!({})));
}

#[tokio::test]
async fn internal_routes_need_the_shared_secret() {
    let Some(api) = Api::new().await else { return };
    let a = api.db.named("alice").await;
    let b = api.db.named("bob").await;
    api.db.friends(a, b).await;
    let paths = [
        ("POST", "/internal/relations", Some(json!({ "viewer": a, "others": [b] }))),
        ("GET", &format!("/internal/friends/{a}"), None),
        ("POST", "/internal/verify", Some(json!({ "token": "x" }))),
        ("POST", "/internal/text-check", Some(json!({ "text": "salut" }))),
        ("POST", "/internal/profiles", Some(json!({ "ids": [a] }))),
    ];
    for (m, p, body) in &paths {
        assert_eq!(api.call(m, p, None, body.clone()).await.0, StatusCode::FORBIDDEN, "{p}");
        let wrong = api.call_with(m, p, &[("x-sona-internal", "mauvais".to_string())], body.clone()).await;
        assert_eq!(wrong.0, StatusCode::FORBIDDEN, "{p}");
        // Un jeton d'utilisateur ne remplace pas le secret.
        assert_eq!(api.call(m, p, Some(&api.token(a)), body.clone()).await.0, StatusCode::FORBIDDEN, "{p}");
    }
    let (st, r) = api.internal("POST", "/internal/relations", Some(json!({ "viewer": a, "others": [b] }))).await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(r[b.to_string()]["friend"], true);
    assert_eq!(api.internal("GET", &format!("/internal/friends/{a}"), None).await.1["friends"], json!([b]));
    assert_eq!(api.internal("POST", "/internal/text-check", Some(json!({ "text": "H1tl3r" }))).await.1["offensive"], true);
    assert_eq!(api.internal("POST", "/internal/text-check", Some(json!({ "text": "dominique" }))).await.1["offensive"], false);
    let (_, v) = api.internal("POST", "/internal/verify", Some(json!({ "token": api.token(a) }))).await;
    assert_eq!(v["user_id"], a.to_string());
    let (st, _) = api.internal("POST", "/internal/notify/session-invite", Some(json!({ "user_id": b, "payload": { "code": "ABCD" } }))).await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(api.db.su_scalar(&format!("select count(*) from public.notifications where user_id = '{b}' and kind = 'session_invite'")).await, "1");
    // Sans secret configuré : tout est fermé.
    let Some(closed) = Api::with(|cfg, _| cfg.internal_secret = None).await else { return };
    assert_eq!(closed.call_with("POST", "/internal/text-check", &[("x-sona-internal", "".into())], Some(json!({ "text": "x" }))).await.0, StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn admin_content_and_session_actions_are_audited_and_forwarded() {
    let music = common::mock::start(|_| (200, "{}".to_string())).await;
    let url = music.url.clone();
    let Some(api) = Api::with(move |cfg, _| cfg.music_internal_url = Some(url)).await else { return };
    let (_, modo) = staff(&api, "modo", "moderator").await;
    let owner = api.db.named("proprio").await;
    let (st, _) = api.call("POST", "/admin/content", Some(&modo), Some(json!({ "action": "hide", "kind": "playlist", "owner": owner, "ref": "42", "reason": "contenu choquant" }))).await;
    assert_eq!(st, StatusCode::OK);
    let (st, _) = api.call("POST", "/admin/session", Some(&modo), Some(json!({ "code": "ABCD", "action": "kick", "user": owner, "reason": "propos déplacés" }))).await;
    assert_eq!(st, StatusCode::OK);
    let seen = music.requests();
    assert_eq!(seen.len(), 2);
    assert_eq!(seen[0].uri, "/internal/content/playlist/42/hide");
    assert_eq!(seen[0].headers["x-sona-internal"], "internal-test-secret");
    assert_eq!(seen[1].uri, "/internal/sessions/ABCD/kick");
    assert_eq!(api.db.su_scalar("select count(*) from public.audit_log where action in ('content.hide','session.kick')").await, "2");
    // Références piégées refusées avant tout appel.
    for bad in ["../../etc", "42/delete", "a b", ""] {
        let (st, _) = api.call("POST", "/admin/content", Some(&modo), Some(json!({ "action": "hide", "kind": "playlist", "owner": owner, "ref": bad, "reason": "motif valable" }))).await;
        assert_eq!(st, StatusCode::BAD_REQUEST, "{bad:?}");
    }
    assert_eq!(music.requests().len(), 2);
    // Sans serveur musique configuré : erreur claire, mais l'action est journalisée avant.
    let Some(alone) = Api::new().await else { return };
    let (_, m2) = staff(&alone, "modo", "moderator").await;
    let o2 = alone.db.named("proprio").await;
    let (st, _) = alone.call("POST", "/admin/content", Some(&m2), Some(json!({ "action": "delete", "kind": "playlist", "owner": o2, "ref": "1", "reason": "motif valable" }))).await;
    assert_eq!(st, StatusCode::SERVICE_UNAVAILABLE);
}

#[tokio::test]
async fn cors_only_allows_listed_origins() {
    let Some(api) = Api::with(|cfg, _| cfg.cors_origins = vec!["https://trysona.fr".into()]).await else { return };
    async fn pre(api: &Api, origin: &str) -> Option<String> {
        use axum::body::Body;
        use axum::http::Request;
        use tower::ServiceExt;
        let req = Request::builder().method("OPTIONS").uri("/me").header("origin", origin).header("access-control-request-method", "GET").header("access-control-request-headers", "authorization").body(Body::empty()).unwrap();
        let resp = sona_accounts::routes::router(api.state.clone()).oneshot(req).await.unwrap();
        resp.headers().get("access-control-allow-origin").map(|v| v.to_str().unwrap().to_string())
    }
    assert_eq!(pre(&api, "https://trysona.fr").await.as_deref(), Some("https://trysona.fr"));
    assert_eq!(pre(&api, "https://evil.example").await, None);
}
