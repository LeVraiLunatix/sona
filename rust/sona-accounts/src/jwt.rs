//! Vérification des jetons d'accès Supabase : HS256 (secret JWT des anciens
//! projets) ou clés publiques du JWKS (ES256 / RS256, projets récents).
//! Algorithme choisi par NOUS d'après la clé connue, jamais « none », jamais
//! un secret HMAC utilisé comme clé publique.

use crate::error::AppError;
use jsonwebtoken::jwk::JwkSet;
use jsonwebtoken::{decode, decode_header, Algorithm, DecodingKey, Validation};
use serde::Deserialize;
use std::collections::HashMap;
use std::sync::RwLock;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub exp: u64,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub email: Option<String>,
    #[serde(default)]
    pub session_id: Option<String>,
}

struct KeyCache {
    fetched: Option<Instant>,
    keys: HashMap<String, (Algorithm, DecodingKey)>,
}

pub struct JwtVerifier {
    hmac: Option<DecodingKey>,
    jwks_url: Option<String>,
    http: reqwest::Client,
    cache: RwLock<KeyCache>,
}

const JWKS_TTL: Duration = Duration::from_secs(600);
/// Pas plus d'un rechargement du JWKS toutes les 30 s (jeton avec un `kid` inconnu).
const JWKS_MIN_REFETCH: Duration = Duration::from_secs(30);

impl JwtVerifier {
    pub fn new(hmac_secret: Option<&str>, jwks_url: Option<String>) -> Self {
        JwtVerifier {
            hmac: hmac_secret.map(|s| DecodingKey::from_secret(s.as_bytes())),
            jwks_url,
            http: reqwest::Client::builder().timeout(Duration::from_secs(5)).build().expect("client HTTP"),
            cache: RwLock::new(KeyCache { fetched: None, keys: HashMap::new() }),
        }
    }

    /// Clés publiques déjà connues (tests, ou JWKS pré-chargé).
    pub fn with_jwks_json(self, json: &str) -> Self {
        if let Ok(set) = serde_json::from_str::<JwkSet>(json) {
            let mut cache = self.cache.write().unwrap();
            cache.keys = keys_from(&set);
            cache.fetched = Some(Instant::now());
        }
        self
    }

    pub async fn verify(&self, token: &str) -> Result<Claims, AppError> {
        let header = decode_header(token).map_err(|_| AppError::Unauthorized)?;
        let (alg, key) = match header.alg {
            Algorithm::HS256 => (Algorithm::HS256, self.hmac.clone().ok_or(AppError::Unauthorized)?),
            Algorithm::ES256 | Algorithm::RS256 => {
                let kid = header.kid.ok_or(AppError::Unauthorized)?;
                let (a, k) = self.key_for(&kid).await.ok_or(AppError::Unauthorized)?;
                if a != header.alg {
                    return Err(AppError::Unauthorized);
                }
                (a, k)
            }
            _ => return Err(AppError::Unauthorized),
        };
        let mut validation = Validation::new(alg);
        validation.set_audience(&["authenticated"]);
        validation.set_required_spec_claims(&["exp", "sub", "aud"]);
        validation.leeway = 5;
        let data = decode::<Claims>(token, &key, &validation).map_err(|_| AppError::Unauthorized)?;
        // Les clés `anon` / `service_role` de Supabase sont aussi des JWT valides : refusées ici.
        if data.claims.role.as_deref() != Some("authenticated") {
            return Err(AppError::Unauthorized);
        }
        Ok(data.claims)
    }

    async fn key_for(&self, kid: &str) -> Option<(Algorithm, DecodingKey)> {
        {
            let cache = self.cache.read().unwrap();
            let fresh = cache.fetched.map(|t| t.elapsed() < JWKS_TTL).unwrap_or(false);
            if let Some(k) = cache.keys.get(kid) {
                if fresh {
                    return Some(k.clone());
                }
            }
        }
        let url = self.jwks_url.clone()?;
        {
            let cache = self.cache.read().unwrap();
            if let Some(t) = cache.fetched {
                if t.elapsed() < JWKS_MIN_REFETCH {
                    return cache.keys.get(kid).cloned();
                }
            }
        }
        let fetched = async {
            let set: JwkSet = self.http.get(&url).send().await.ok()?.json().await.ok()?;
            Some(keys_from(&set))
        }
        .await;
        let mut cache = self.cache.write().unwrap();
        cache.fetched = Some(Instant::now());
        if let Some(keys) = fetched {
            cache.keys = keys;
        }
        cache.keys.get(kid).cloned()
    }
}

fn keys_from(set: &JwkSet) -> HashMap<String, (Algorithm, DecodingKey)> {
    let mut out = HashMap::new();
    for jwk in &set.keys {
        let Some(kid) = jwk.common.key_id.clone() else { continue };
        let alg = match jwk.common.key_algorithm {
            Some(jsonwebtoken::jwk::KeyAlgorithm::ES256) => Algorithm::ES256,
            Some(jsonwebtoken::jwk::KeyAlgorithm::RS256) => Algorithm::RS256,
            _ => continue,
        };
        if let Ok(key) = DecodingKey::from_jwk(jwk) {
            out.insert(kid, (alg, key));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use jsonwebtoken::{encode, EncodingKey, Header};
    use serde_json::json;

    const SECRET: &str = "un-secret-hmac-de-test-assez-long-32";

    fn now() -> u64 {
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs()
    }

    fn token(claims: serde_json::Value, secret: &str) -> String {
        encode(&Header::new(Algorithm::HS256), &claims, &EncodingKey::from_secret(secret.as_bytes())).unwrap()
    }

    fn good() -> serde_json::Value {
        json!({ "sub": "11111111-1111-1111-1111-111111111111", "aud": "authenticated", "role": "authenticated", "exp": now() + 600 })
    }

    #[tokio::test]
    async fn accepts_a_valid_token() {
        let v = JwtVerifier::new(Some(SECRET), None);
        let c = v.verify(&token(good(), SECRET)).await.unwrap();
        assert_eq!(c.sub, "11111111-1111-1111-1111-111111111111");
    }

    #[tokio::test]
    async fn rejects_expired_wrong_secret_wrong_role_wrong_audience() {
        let v = JwtVerifier::new(Some(SECRET), None);
        let mut expired = good();
        expired["exp"] = json!(now() - 3600);
        assert!(v.verify(&token(expired, SECRET)).await.is_err());
        assert!(v.verify(&token(good(), "autre-secret-autre-secret-autre-32")).await.is_err());
        let mut anon = good();
        anon["role"] = json!("anon");
        assert!(v.verify(&token(anon, SECRET)).await.is_err());
        let mut service = good();
        service["role"] = json!("service_role");
        assert!(v.verify(&token(service, SECRET)).await.is_err());
        let mut aud = good();
        aud["aud"] = json!("autre");
        assert!(v.verify(&token(aud, SECRET)).await.is_err());
    }

    #[tokio::test]
    async fn rejects_alg_none_garbage_and_missing_key() {
        let v = JwtVerifier::new(Some(SECRET), None);
        // alg: none, signature vide.
        let none = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ4IiwiYXVkIjoiYXV0aGVudGljYXRlZCIsInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjo5OTk5OTk5OTk5fQ.";
        assert!(v.verify(none).await.is_err());
        assert!(v.verify("pas.un.jeton").await.is_err());
        assert!(v.verify("").await.is_err());
        // Sans secret HMAC configuré, un jeton HS256 ne passe jamais.
        let no_secret = JwtVerifier::new(None, None);
        assert!(no_secret.verify(&token(good(), SECRET)).await.is_err());
    }
}
