//! Last.fm avec un faux serveur : connexion, secret chiffré, signature,
//! scrobbling avec file d'attente et réessais, erreurs.

mod common;
use axum::http::StatusCode;
use common::{form, mock, Api};
use serde_json::json;
use std::sync::Arc;
use uuid::Uuid;

const SECRET: &str = "secretfake";

/// Vérifie la signature comme le ferait Last.fm.
fn signature_ok(params: &std::collections::BTreeMap<String, String>) -> bool {
    let mut p: std::collections::BTreeMap<&str, String> = std::collections::BTreeMap::new();
    for (k, v) in params {
        if k != "api_sig" {
            p.insert(k.as_str(), v.clone());
        }
    }
    sona_accounts::lastfm_sig::sign(&p, SECRET) == params.get("api_sig").cloned().unwrap_or_default()
}

fn params_of(s: &mock::Seen) -> std::collections::BTreeMap<String, String> {
    if s.method == "GET" {
        form(s.uri.split_once('?').map(|x| x.1).unwrap_or(""))
    } else {
        form(&s.body)
    }
}

async fn api_with(handler: impl Fn(&mock::Seen) -> (u16, String) + Send + Sync + 'static) -> Option<(Api, mock::Server)> {
    let server = mock::start(move |s| {
        // Un serveur qui accepte une signature fausse ne prouve rien : on la contrôle toujours.
        if !signature_ok(&params_of(s)) {
            return (403, json!({ "error": 13, "message": "Invalid method signature supplied" }).to_string());
        }
        handler(s)
    })
    .await;
    let base = format!("{}/", server.url);
    let api = Api::with(move |_, st| st.lastfm_base = Arc::new(base)).await?;
    Some((api, server))
}

async fn connect(api: &Api, user: Uuid) {
    let (st, body) = api.call("POST", "/lastfm/connect", Some(&api.token(user)), Some(json!({ "token": "abcdefghijklmnopqrstuvwx012345" }))).await;
    assert_eq!(st, StatusCode::OK, "{body}");
}

fn session_ok(s: &mock::Seen) -> (u16, String) {
    let p = params_of(s);
    match p.get("method").map(String::as_str) {
        Some("auth.getSession") => (200, json!({ "session": { "name": "lfm_alice", "key": "SESSION-KEY-123", "subscriber": 0 } }).to_string()),
        _ => (200, json!({ "scrobbles": { "@attr": { "accepted": 1 } } }).to_string()),
    }
}

#[tokio::test]
async fn start_only_accepts_allowed_return_urls() {
    let Some(api) = Api::new().await else { return };
    let u = api.db.named("alice").await;
    let t = api.token(u);
    let (st, b) = api.call("POST", "/lastfm/start", Some(&t), Some(json!({ "return_to": "https://trysona.fr/web/" }))).await;
    assert_eq!(st, StatusCode::OK);
    let url = b["auth_url"].as_str().unwrap();
    assert!(url.starts_with("https://www.last.fm/api/auth/?api_key=clefake&cb=https%3A%2F%2Ftrysona.fr%2Fweb%2F"), "{url}");
    assert!(!url.contains("secretfake"), "le secret n'apparaît jamais");
    for bad in ["https://evil.example/", "https://trysona.fr.evil.example/", "javascript:alert(1)", "https://trysona.fr@evil.example/", ""] {
        let (st, _) = api.call("POST", "/lastfm/start", Some(&t), Some(json!({ "return_to": bad }))).await;
        assert_eq!(st, StatusCode::BAD_REQUEST, "{bad:?}");
    }
    assert_eq!(api.call("POST", "/lastfm/start", None, Some(json!({ "return_to": "https://trysona.fr/" }))).await.0, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn connect_exchanges_the_token_server_side_and_stores_an_encrypted_key() {
    let Some((api, server)) = api_with(session_ok).await else { return };
    let u = api.db.named("alice").await;
    connect(&api, u).await;
    let req = &server.requests()[0];
    let p = params_of(req);
    assert_eq!(p["method"], "auth.getSession");
    assert_eq!(p["api_key"], "clefake");
    assert!(!req.uri.contains(SECRET) && !req.body.contains(SECRET), "le secret ne sort jamais, seule la signature");
    // Stockage : jamais en clair, lié au compte.
    let stored = api.db.su_scalar(&format!("select secret_encrypted from public.connected_services where user_id = '{u}'")).await;
    assert!(stored.starts_with("v1.") && !stored.contains("SESSION-KEY-123"));
    let vault = api.state.vault.as_ref().unwrap();
    assert_eq!(vault.open(&stored, &u.to_string()).unwrap(), "SESSION-KEY-123");
    assert!(vault.open(&stored, &Uuid::new_v4().to_string()).is_err());
    // Le client voit qu'il est connecté, jamais la clé.
    let (_, st) = api.call("GET", "/lastfm/status", Some(&api.token(u)), None).await;
    assert_eq!(st, json!({ "connected": true, "username": "lfm_alice", "last_error": null, "last_sync_at": null }));
    let rows = api.db.q(common::Who::User(u), "select provider, external_username from public.connected_services").await.unwrap();
    assert_eq!(rows, json!([{ "provider": "lastfm", "external_username": "lfm_alice" }]));
    // Déconnexion : la clé est supprimée.
    let (st, _) = api.call("DELETE", "/lastfm", Some(&api.token(u)), None).await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(api.db.su_scalar("select count(*) from public.connected_services").await, "0");
}

#[tokio::test]
async fn connect_errors_are_clear_and_tokens_are_validated_first() {
    let Some((api, server)) = api_with(|s| match params_of(s).get("token").map(String::as_str) {
        Some("pasencoreautorise000000000000") => (403, json!({ "error": 14, "message": "Unauthorized Token" }).to_string()),
        Some("tokenexpire00000000000000000") => (403, json!({ "error": 4, "message": "Invalid token" }).to_string()),
        Some("limite000000000000000000000") => (429, json!({ "error": 29, "message": "Rate limit exceeded" }).to_string()),
        _ => (200, "{}".to_string()),
    })
    .await
    else {
        return;
    };
    let u = api.db.named("alice").await;
    let t = api.token(u);
    let go = |token: &'static str| {
        let (api, t) = (&api, t.clone());
        async move { api.call("POST", "/lastfm/connect", Some(&t), Some(json!({ "token": token }))).await }
    };
    let (st, b) = go("pasencoreautorise000000000000").await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
    assert!(b["message"].as_str().unwrap().contains("Autorise d'abord Sona"));
    let (st, b) = go("tokenexpire00000000000000000").await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
    assert!(b["message"].as_str().unwrap().contains("expiré"));
    assert_eq!(go("limite000000000000000000000").await.0, StatusCode::TOO_MANY_REQUESTS);
    // Jeton douteux : refusé sans appel réseau.
    let before = server.requests().len();
    assert_eq!(go("court").await.0, StatusCode::BAD_REQUEST);
    assert_eq!(server.requests().len(), before);
    // Réponse inattendue : erreur propre, rien en base.
    assert_eq!(go("quelconque00000000000000000").await.0, StatusCode::BAD_GATEWAY);
    assert_eq!(api.db.su_scalar("select count(*) from public.connected_services").await, "0");
}

#[tokio::test]
async fn connect_is_unavailable_without_the_encryption_key() {
    let server = mock::start(session_ok).await;
    let base = format!("{}/", server.url);
    let Some(api) = Api::with(move |cfg, st| {
        cfg.secrets_key = None;
        st.lastfm_base = Arc::new(base);
    })
    .await
    else {
        return;
    };
    let u = api.db.named("alice").await;
    let (st, _) = api.call("POST", "/lastfm/connect", Some(&api.token(u)), Some(json!({ "token": "abcdefghijklmnopqrstuvwx012345" }))).await;
    assert_eq!(st, StatusCode::SERVICE_UNAVAILABLE);
    assert!(server.requests().is_empty(), "pas d'échange si on ne peut pas chiffrer");
}

fn scrobble_in(user: Uuid, kind: &str, title: &str, age_secs: i64) -> serde_json::Value {
    json!({ "user_id": user, "kind": kind, "artist": "Daft Punk", "track": title, "album": "Discovery", "duration": 224,
            "timestamp": chrono::Utc::now().timestamp() - age_secs })
}

#[tokio::test]
async fn scrobbles_are_queued_then_sent_signed_in_batches() {
    let Some((api, server)) = api_with(session_ok).await else { return };
    let u = api.db.named("alice").await;
    connect(&api, u).await;
    for (i, title) in ["One More Time", "Aerodynamic", "Digital Love"].iter().enumerate() {
        let (st, b) = api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "scrobble", title, 600 - i as i64 * 200))).await;
        assert_eq!((st, &b["queued"]), (StatusCode::OK, &json!(true)));
    }
    api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "now_playing", "Veridis Quo", 0))).await;
    api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "now_playing", "Voyager", 0))).await;
    assert_eq!(api.db.su_scalar("select count(*) from private.scrobble_queue where kind = 'now_playing'").await, "1", "un seul « en cours »");
    assert_eq!(sona_accounts::lastfm::tick(&api.state).await.unwrap(), 4);
    let reqs: Vec<_> = server.requests().into_iter().skip(1).collect();
    assert_eq!(reqs.len(), 2, "un lot de scrobbles + un « now playing »");
    let batch = params_of(&reqs[0]);
    assert_eq!(batch["method"], "track.scrobble");
    assert_eq!(batch["sk"], "SESSION-KEY-123");
    assert_eq!(batch["artist[0]"], "Daft Punk");
    assert_eq!(batch["track[2]"], "Digital Love");
    assert_eq!(batch["album[1]"], "Discovery");
    assert_eq!(reqs[0].method, "POST");
    let np = params_of(&reqs[1]);
    assert_eq!((np["method"].as_str(), np["track"].as_str()), ("track.updateNowPlaying", "Voyager"));
    assert_eq!(api.db.su_scalar("select count(*) from private.scrobble_queue").await, "0");
    let status = api.call("GET", "/lastfm/status", Some(&api.token(u)), None).await.1;
    assert!(status["last_sync_at"].is_string() && status["last_error"].is_null());
}

#[tokio::test]
async fn nothing_is_queued_without_a_connection_or_when_scrobbling_is_off_or_data_is_bad() {
    let Some((api, _server)) = api_with(session_ok).await else { return };
    let u = api.db.named("alice").await;
    let q = |body| api.internal("POST", "/internal/scrobble", Some(body));
    // Non connecté.
    assert_eq!(q(scrobble_in(u, "scrobble", "T", 100)).await.1["queued"], false);
    connect(&api, u).await;
    // Scrobbling coupé dans les réglages.
    api.db.su(&format!("update public.user_settings set scrobbling_enabled = false where user_id = '{u}'")).await;
    assert_eq!(q(scrobble_in(u, "scrobble", "T", 100)).await.1["queued"], false);
    api.db.su(&format!("update public.user_settings set scrobbling_enabled = true where user_id = '{u}'")).await;
    assert_eq!(q(scrobble_in(u, "scrobble", "T", 100)).await.1["queued"], true);
    // Données invalides.
    assert_eq!(q(scrobble_in(u, "scrobble", "T", 15 * 86400)).await.0, StatusCode::BAD_REQUEST, "plus de 14 jours");
    assert_eq!(q(scrobble_in(u, "scrobble", "T", -3600)).await.0, StatusCode::BAD_REQUEST, "dans le futur");
    assert_eq!(q(scrobble_in(u, "scrobble", "   ", 100)).await.0, StatusCode::BAD_REQUEST);
    assert_eq!(q(scrobble_in(u, "explose", "T", 100)).await.0, StatusCode::BAD_REQUEST);
    assert_eq!(q(json!({ "user_id": u, "kind": "scrobble", "artist": "A", "track": "x".repeat(300), "timestamp": chrono::Utc::now().timestamp() })).await.0, StatusCode::BAD_REQUEST);
    // Uniquement via le secret interne.
    assert_eq!(api.call("POST", "/internal/scrobble", Some(&api.token(u)), Some(scrobble_in(u, "scrobble", "T", 100))).await.0, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn transient_failures_are_retried_with_backoff_and_nothing_is_lost() {
    let outage = Arc::new(std::sync::atomic::AtomicU8::new(0));
    let flag = outage.clone();
    let Some((api, server)) = api_with(move |s| {
        let p = params_of(s);
        if p.get("method").map(String::as_str) == Some("auth.getSession") {
            return session_ok(s);
        }
        match flag.load(std::sync::atomic::Ordering::SeqCst) {
            1 => (500, "<html>oups</html>".to_string()),
            2 => (200, json!({ "error": 11, "message": "Service offline" }).to_string()),
            3 => (429, json!({ "error": 29, "message": "Rate Limit Exceeded" }).to_string()),
            _ => session_ok(s),
        }
    })
    .await
    else {
        return;
    };
    let u = api.db.named("alice").await;
    connect(&api, u).await;
    api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "scrobble", "Titre", 100))).await;
    let due_now = || api.db.su_scalar("select count(*) from private.scrobble_queue where next_attempt_at <= now()");
    for (code, expect_in_error) in [(1u8, "indisponible"), (2, "indisponible"), (3, "limite")] {
        outage.store(code, std::sync::atomic::Ordering::SeqCst);
        api.db.su("update private.scrobble_queue set next_attempt_at = now()").await;
        sona_accounts::lastfm::tick(&api.state).await.unwrap();
        assert_eq!(api.db.su_scalar("select count(*) from private.scrobble_queue").await, "1", "rien de perdu (panne {code})");
        assert_eq!(due_now().await, "0", "réessai repoussé (panne {code})");
        let st = api.call("GET", "/lastfm/status", Some(&api.token(u)), None).await.1;
        assert!(st["last_error"].as_str().unwrap().contains(expect_in_error), "{st}");
        // Un passage trop tôt n'appelle pas Last.fm.
        let n = server.requests().len();
        assert_eq!(sona_accounts::lastfm::tick(&api.state).await.unwrap(), 0);
        assert_eq!(server.requests().len(), n);
    }
    assert_eq!(api.db.su_scalar("select attempts from private.scrobble_queue").await, "3");
    // Last.fm revient : l'écoute part, l'erreur disparaît.
    outage.store(0, std::sync::atomic::Ordering::SeqCst);
    api.db.su("update private.scrobble_queue set next_attempt_at = now()").await;
    sona_accounts::lastfm::tick(&api.state).await.unwrap();
    assert_eq!(api.db.su_scalar("select count(*) from private.scrobble_queue").await, "0");
    assert!(api.call("GET", "/lastfm/status", Some(&api.token(u)), None).await.1["last_error"].is_null());
}

#[tokio::test]
async fn a_revoked_key_disconnects_cleanly_with_a_clear_message() {
    let Some((api, _s)) = api_with(|s| {
        if params_of(s).get("method").map(String::as_str) == Some("auth.getSession") {
            session_ok(s)
        } else {
            (403, json!({ "error": 9, "message": "Invalid session key - Please re-authenticate" }).to_string())
        }
    })
    .await
    else {
        return;
    };
    let u = api.db.named("alice").await;
    connect(&api, u).await;
    api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "scrobble", "A", 300))).await;
    api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "scrobble", "B", 200))).await;
    sona_accounts::lastfm::tick(&api.state).await.unwrap();
    assert_eq!(api.db.su_scalar("select count(*) from private.scrobble_queue").await, "0", "inutile de réessayer");
    let st = api.call("GET", "/lastfm/status", Some(&api.token(u)), None).await.1;
    assert_eq!(st["connected"], false);
    assert!(st["last_error"].as_str().unwrap().contains("révoqué"));
    // Plus rien n'est mis en file tant qu'on ne s'est pas reconnecté.
    assert_eq!(api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "scrobble", "C", 100))).await.1["queued"], false);
}

#[tokio::test]
async fn disconnecting_drops_pending_items_and_the_lastfm_username_is_exposed_to_the_music_server() {
    let Some((api, _s)) = api_with(session_ok).await else { return };
    let u = api.db.named("alice").await;
    assert_eq!(api.internal("GET", &format!("/internal/lastfm/{u}"), None).await.1["username"], json!(null));
    connect(&api, u).await;
    assert_eq!(api.internal("GET", &format!("/internal/lastfm/{u}"), None).await.1["username"], "lfm_alice");
    api.internal("POST", "/internal/scrobble", Some(scrobble_in(u, "scrobble", "A", 100))).await;
    api.call("DELETE", "/lastfm", Some(&api.token(u)), None).await;
    assert_eq!(api.db.su_scalar("select count(*) from private.scrobble_queue").await, "0");
    assert_eq!(sona_accounts::lastfm::tick(&api.state).await.unwrap(), 0);
}

#[tokio::test]
async fn installed_apps_use_a_server_side_token_instead_of_a_redirect() {
    let Some((api, server)) = api_with_gotoken().await else { return };
    let u = api.db.named("alice").await;
    let (st, b) = api.call("POST", "/lastfm/start", Some(&api.token(u)), Some(json!({}))).await;
    assert_eq!(st, StatusCode::OK, "{b}");
    let url = b["auth_url"].as_str().unwrap();
    assert!(url.contains("api_key=clefake") && url.contains("token=0123456789abcdef0123456789abcdef"), "{url}");
    assert!(!url.contains("cb="), "pas d'adresse de retour dans ce flux");
    assert_eq!(b["token"], "0123456789abcdef0123456789abcdef");
    assert_eq!(params_of(&server.requests()[0])["method"], "auth.getToken");
    // Tant que l'utilisateur n'a pas autorisé, la connexion répond « pas encore » (l'app réessaie).
    let (st, b) = api.call("POST", "/lastfm/connect", Some(&api.token(u)), Some(json!({ "token": "0123456789abcdef0123456789abcdef" }))).await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
    assert!(b["message"].as_str().unwrap().contains("Autorise d'abord"));
}

async fn api_with_gotoken() -> Option<(Api, mock::Server)> {
    api_with(|s| match params_of(s).get("method").map(String::as_str) {
        Some("auth.getToken") => (200, json!({ "token": "0123456789abcdef0123456789abcdef" }).to_string()),
        _ => (403, json!({ "error": 14, "message": "Unauthorized Token - This token has not been authorized" }).to_string()),
    })
    .await
}
