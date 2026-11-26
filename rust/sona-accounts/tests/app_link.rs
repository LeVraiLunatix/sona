//! Connexion d'une application par le navigateur : code à usage unique lié au secret de l'application.

mod common;
use axum::http::StatusCode;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use common::{mock, Api};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const VERIFIER: &str = "le-secret-reste-dans-l-application-0123456789";

fn challenge(v: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(v.as_bytes()))
}

async fn setup() -> Option<(Api, mock::Server)> {
    let gotrue = mock::start(|_| (200, json!({ "hashed_token": "HASH123" }).to_string())).await;
    let url = gotrue.url.clone();
    let api = Api::with(move |cfg, _| {
        cfg.supabase_url = url;
        cfg.supabase_service_key = Some("service-key-test".into());
    })
    .await?;
    Some((api, gotrue))
}

async fn code_for(api: &Api, user: uuid::Uuid) -> String {
    let (st, b) = api.call("POST", "/app-link", Some(&api.token(user)), Some(json!({ "challenge": challenge(VERIFIER) }))).await;
    assert_eq!(st, StatusCode::OK, "{b}");
    b["code"].as_str().unwrap().to_string()
}

async fn exchange(api: &Api, code: &str, verifier: &str) -> (StatusCode, Value) {
    api.call("POST", "/app-link/exchange", None, Some(json!({ "code": code, "verifier": verifier }))).await
}

#[tokio::test]
async fn the_app_gets_one_session_with_its_own_secret() {
    let Some((api, gotrue)) = setup().await else { return };
    let u = api.db.named("alice").await;
    let code = code_for(&api, u).await;
    // Le code n'est pas gardé en clair.
    assert_eq!(api.db.su_scalar(&format!("select count(*) from private.app_links where code_hash = '{code}'")).await, "0");
    let (st, out) = exchange(&api, &code, VERIFIER).await;
    assert_eq!(st, StatusCode::OK, "{out}");
    assert_eq!(out, json!({ "token_hash": "HASH123", "type": "email" }));
    assert_eq!(gotrue.requests().len(), 1);
    // Une seule fois.
    assert_eq!(exchange(&api, &code, VERIFIER).await.0, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn a_stolen_or_old_code_is_useless() {
    let Some((api, gotrue)) = setup().await else { return };
    let u = api.db.named("alice").await;
    let code = code_for(&api, u).await;
    assert_eq!(exchange(&api, &code, "un-autre-secret").await.0, StatusCode::BAD_REQUEST);
    // L'essai raté a brûlé le code.
    assert_eq!(exchange(&api, &code, VERIFIER).await.0, StatusCode::BAD_REQUEST);
    let late = code_for(&api, u).await;
    api.db.su("update private.app_links set expires_at = now() - interval '1 second'").await;
    assert_eq!(exchange(&api, &late, VERIFIER).await.0, StatusCode::BAD_REQUEST);
    assert_eq!(gotrue.requests().len(), 0, "aucune session fabriquée");
}

#[tokio::test]
async fn asking_needs_a_real_signed_in_account() {
    let Some((api, _g)) = setup().await else { return };
    let (st, _) = api.call("POST", "/app-link", None, Some(json!({ "challenge": challenge(VERIFIER) }))).await;
    assert_eq!(st, StatusCode::UNAUTHORIZED);
    let u = api.db.named("alice").await;
    let (st, _) = api.call("POST", "/app-link", Some(&api.token(u)), Some(json!({ "challenge": "court" }))).await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
    // Un invité (sans adresse) ne peut pas connecter une application.
    api.db.su(&format!("update auth.users set email = null where id = '{u}'")).await;
    let (st, _) = api.call("POST", "/app-link", Some(&api.token(u)), Some(json!({ "challenge": challenge(VERIFIER) }))).await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
}
