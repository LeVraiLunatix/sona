//! Passkeys : un authentificateur logiciel (SoftToken) fait le vrai aller-retour
//! WebAuthn contre les routes du service.

mod common;
use axum::http::StatusCode;
use common::{mock, Api};
use serde_json::json;
use url::Url;
use webauthn_authenticator_rs::softtoken::SoftToken;
use webauthn_authenticator_rs::AuthenticatorBackend;
use webauthn_rs::prelude::{CreationChallengeResponse, RequestChallengeResponse};

fn origin() -> Url {
    Url::parse("http://localhost:8000").unwrap()
}

/// Les authentificateurs logiciels de test ne savent pas créer de clé « découvrable » :
/// on les fait agir comme un iPhone ou Windows Hello (qui le font toujours), en
/// ajustant les options reçues et la réponse (le `userHandle` n'est pas signé).
async fn register(api: &Api, token: &str, soft: &mut SoftToken) -> StatusCode {
    let (st, start) = api.call("POST", "/passkey/register/start", Some(token), None).await;
    assert_eq!(st, StatusCode::OK, "{start}");
    // Le serveur exige bien une clé découvrable.
    assert_eq!(start["options"]["publicKey"]["authenticatorSelection"]["residentKey"], "required");
    let mut options = start["options"].clone();
    options["publicKey"]["authenticatorSelection"]["requireResidentKey"] = json!(false);
    options["publicKey"]["authenticatorSelection"]["residentKey"] = json!("discouraged");
    let ccr: CreationChallengeResponse = serde_json::from_value(options).unwrap();
    let cred = soft.perform_register(origin(), ccr.public_key, 60_000).expect("enregistrement logiciel");
    api.call("POST", "/passkey/register/finish", Some(token), Some(json!({ "challenge_id": start["challenge_id"], "credential": cred, "device_name": "Mon iPhone" }))).await.0
}

async fn login(api: &Api, soft: &mut SoftToken) -> (StatusCode, serde_json::Value, serde_json::Value) {
    let (st, start) = api.call("POST", "/passkey/login/start", None, None).await;
    assert_eq!(st, StatusCode::OK, "{start}");
    // Connexion sans e-mail : aucune liste de clés autorisées envoyée par le serveur.
    assert_eq!(start["options"]["publicKey"]["allowCredentials"].as_array().map(Vec::len).unwrap_or(0), 0);
    let mut options = start["options"].clone();
    let (cred_id, user_id): (String, uuid::Uuid) = sqlx::query_as("select credential_id, user_id from public.passkey_credentials limit 1").fetch_one(&api.db.pool).await.unwrap();
    options["publicKey"]["allowCredentials"] = json!([{ "type": "public-key", "id": cred_id }]);
    let rcr: RequestChallengeResponse = serde_json::from_value(options).unwrap();
    let cred = soft.perform_auth(origin(), rcr.public_key, 60_000).expect("authentification logicielle");
    let mut cred = serde_json::to_value(&cred).unwrap();
    use base64::Engine;
    cred["response"]["userHandle"] = json!(base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(user_id.as_bytes()));
    let (st, out) = api.call("POST", "/passkey/login/finish", None, Some(json!({ "challenge_id": start["challenge_id"], "credential": cred }))).await;
    (st, out, start)
}

async fn api_with_gotrue() -> Option<(Api, mock::Server)> {
    let gotrue = mock::start(|_| (200, json!({ "hashed_token": "HASH123", "email_otp": "000000" }).to_string())).await;
    let url = gotrue.url.clone();
    let api = Api::with(move |cfg, _| {
        cfg.supabase_url = url;
        cfg.supabase_service_key = Some("service-key-test".into());
    })
    .await?;
    Some((api, gotrue))
}

#[tokio::test]
async fn register_then_log_in_with_a_passkey() {
    let Some((api, gotrue)) = api_with_gotrue().await else { return };
    let u = api.db.named("alice").await;
    let (mut soft, _) = SoftToken::new(true).unwrap();
    assert_eq!(register(&api, &api.token(u), &mut soft).await, StatusCode::OK);
    // Visible dans la liste du compte, sans la clé publique.
    let rows = api.db.q(common::Who::User(u), "select device_name from public.passkey_credentials").await.unwrap();
    assert_eq!(rows, json!([{ "device_name": "Mon iPhone" }]));
    assert!(api.db.q(common::Who::User(u), "select public_key from public.passkey_credentials").await.is_err());

    let (st, out, _) = login(&api, &mut soft).await;
    assert_eq!(st, StatusCode::OK, "{out}");
    assert_eq!(out["token_hash"], "HASH123");
    assert_eq!(out["email"], "alice@example.test");
    assert_eq!(out["type"], "email");
    // La session est demandée à Auth avec la clé de service, jamais envoyée au client.
    let req = &gotrue.requests()[0];
    assert_eq!(req.uri, "/auth/v1/admin/generate_link");
    assert_eq!(req.headers["authorization"], "Bearer service-key-test");
    assert!(!out.to_string().contains("service-key-test"));
    assert!(api.db.su_scalar(&format!("select last_used_at is not null from public.passkey_credentials where user_id = '{u}'")).await == "true");
}

#[tokio::test]
async fn challenges_are_single_use_and_expire() {
    let Some((api, _g)) = api_with_gotrue().await else { return };
    let u = api.db.named("alice").await;
    let (mut soft, _) = SoftToken::new(true).unwrap();
    register(&api, &api.token(u), &mut soft).await;
    // Rejouer une réponse déjà acceptée : refusé.
    let (st, out, start) = login(&api, &mut soft).await;
    assert_eq!(st, StatusCode::OK, "{out}");
    let replay = api.call("POST", "/passkey/login/finish", None, Some(json!({ "challenge_id": start["challenge_id"], "credential": {} }))).await;
    assert!(replay.0.is_client_error(), "{replay:?}");
    assert_eq!(api.db.su_scalar("select count(*) from private.passkey_challenges where kind = 'login'").await, "0", "défi consommé");
    // Défi expiré.
    let (_, start) = api.call("POST", "/passkey/login/start", None, None).await;
    api.db.su("update private.passkey_challenges set expires_at = now() - interval '1 second'").await;
    let (st, _) = api.call("POST", "/passkey/login/finish", None, Some(json!({ "challenge_id": start["challenge_id"], "credential": {} }))).await;
    assert!(st.is_client_error());
    // Défi d'enregistrement d'un autre compte : refusé.
    let other = api.db.named("bob").await;
    let (_, start) = api.call("POST", "/passkey/register/start", Some(&api.token(u)), None).await;
    let mut options = start["options"].clone();
    options["publicKey"]["authenticatorSelection"]["requireResidentKey"] = json!(false);
    options["publicKey"]["authenticatorSelection"]["residentKey"] = json!("discouraged");
    let ccr: CreationChallengeResponse = serde_json::from_value(options).unwrap();
    let (mut soft2, _) = SoftToken::new(true).unwrap();
    let cred = soft2.perform_register(origin(), ccr.public_key, 60_000).unwrap();
    let (st, _) = api.call("POST", "/passkey/register/finish", Some(&api.token(other)), Some(json!({ "challenge_id": start["challenge_id"], "credential": cred }))).await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
    assert_eq!(api.db.su_scalar("select count(*) from public.passkey_credentials").await, "1");
}

#[tokio::test]
async fn an_unknown_authenticator_cannot_log_in() {
    let Some((api, gotrue)) = api_with_gotrue().await else { return };
    let u = api.db.named("alice").await;
    let (mut mine, _) = SoftToken::new(true).unwrap();
    register(&api, &api.token(u), &mut mine).await;
    // Un autre authentificateur n'a pas la clé : jamais de session.
    let (mut stranger, _) = SoftToken::new(true).unwrap();
    let (_, start) = api.call("POST", "/passkey/login/start", None, None).await;
    let mut options = start["options"].clone();
    let cred_id: String = sqlx::query_scalar("select credential_id from public.passkey_credentials").fetch_one(&api.db.pool).await.unwrap();
    options["publicKey"]["allowCredentials"] = json!([{ "type": "public-key", "id": cred_id }]);
    let rcr: RequestChallengeResponse = serde_json::from_value(options).unwrap();
    assert!(stranger.perform_auth(origin(), rcr.public_key, 60_000).is_err());
    // Réponse forgée avec une signature quelconque.
    let (st, _) = api.call("POST", "/passkey/login/finish", None, Some(json!({ "challenge_id": start["challenge_id"],
        "credential": { "id": cred_id, "rawId": cred_id, "type": "public-key", "extensions": {},
          "response": { "authenticatorData": "AAAA", "clientDataJSON": "AAAA", "signature": "AAAA", "userHandle": null } } }))).await;
    assert!(st.is_client_error());
    assert!(gotrue.requests().is_empty());
}

#[tokio::test]
async fn a_sanctioned_account_cannot_get_a_session_with_a_passkey() {
    let Some((api, gotrue)) = api_with_gotrue().await else { return };
    let u = api.db.named("alice").await;
    let (mut soft, _) = SoftToken::new(true).unwrap();
    register(&api, &api.token(u), &mut soft).await;
    api.db.su(&format!("update public.profiles set status = 'banned', status_reason = 'abus' where id = '{u}'")).await;
    let (st, out, _) = login(&api, &mut soft).await;
    assert_eq!(st, StatusCode::FORBIDDEN);
    assert_eq!(out["error"], "sanctioned");
    assert!(gotrue.requests().is_empty(), "aucun lien magique n'est fabriqué");
    // Et un banni ne peut plus enregistrer de nouvelle clé.
    let (st, _) = api.call("POST", "/passkey/register/start", Some(&api.token(u)), None).await;
    assert_eq!(st, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn passkeys_are_limited_and_need_configuration() {
    let Some((api, _g)) = api_with_gotrue().await else { return };
    let u = api.db.named("alice").await;
    for i in 0..10 {
        api.db.su(&format!("insert into public.passkey_credentials (user_id, credential_id, public_key) values ('{u}', 'cred{i}', '{{}}')")).await;
    }
    let (st, b) = api.call("POST", "/passkey/register/start", Some(&api.token(u)), None).await;
    assert_eq!(st, StatusCode::BAD_REQUEST);
    assert!(b["message"].as_str().unwrap().contains("10"));
    let Some(unconfigured) = Api::with(|cfg, _| cfg.webauthn_rp_id = None).await else { return };
    assert_eq!(unconfigured.call("POST", "/passkey/login/start", None, None).await.0, StatusCode::SERVICE_UNAVAILABLE);
    // Sans clé de service, pas de session.
    let (mut soft, _) = SoftToken::new(true).unwrap();
    let Some(nokey) = Api::new().await else { return };
    let v = nokey.db.named("bob").await;
    register(&nokey, &nokey.token(v), &mut soft).await;
    let (st, _, _) = login(&nokey, &mut soft).await;
    assert_eq!(st, StatusCode::SERVICE_UNAVAILABLE);
}
