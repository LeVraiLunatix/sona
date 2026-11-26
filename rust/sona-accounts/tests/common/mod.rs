//! Base Postgres jetable pour les tests SQL / RLS / HTTP.
//!
//! Il faut un Postgres : `eval "$(scripts/test-postgres.sh start)"` exporte
//! SONA_TEST_DATABASE_URL. Sans lui les tests sont ignorés, sauf si
//! SONA_REQUIRE_DB=1 (CI) : alors ils échouent.

#![allow(dead_code)]

use serde_json::Value;
use sqlx::postgres::PgPoolOptions;
use sqlx::{Executor, PgPool};
use uuid::Uuid;

pub const STUB: &str = include_str!("../../../../tests/sql/auth_stub.sql");
pub const MIGRATIONS: &[&str] = &[
    include_str!("../../../../supabase/migrations/20261126000100_core.sql"),
    include_str!("../../../../supabase/migrations/20261126000200_moderation.sql"),
    include_str!("../../../../supabase/migrations/20261126000300_social.sql"),
    include_str!("../../../../supabase/migrations/20261126000400_rls.sql"),
    include_str!("../../../../supabase/migrations/20261126000500_maintenance.sql"),
    include_str!("../../../../supabase/migrations/20261126000600_grants.sql"),
];

#[derive(Clone, Copy)]
pub enum Who {
    Anon,
    User(Uuid),
    Service,
}

pub struct TestDb {
    pub pool: PgPool,
    pub url: String,
}

pub async fn setup() -> Option<TestDb> {
    let Ok(base) = std::env::var("SONA_TEST_DATABASE_URL") else {
        if std::env::var("SONA_REQUIRE_DB").is_ok() {
            panic!("SONA_REQUIRE_DB est défini mais SONA_TEST_DATABASE_URL manque");
        }
        eprintln!("(test ignoré : pas de SONA_TEST_DATABASE_URL, voir scripts/test-postgres.sh)");
        return None;
    };
    let admin = PgPoolOptions::new().max_connections(1).connect(&base).await.expect("connexion Postgres");
    let name = format!("sona_t_{}", Uuid::new_v4().simple());
    // Les rôles sont globaux au serveur : création sérialisée par un verrou.
    let mut conn = admin.acquire().await.unwrap();
    sqlx::query("select pg_advisory_lock(424242)").execute(&mut *conn).await.unwrap();
    sqlx::raw_sql(&format!("create database {name}")).execute(&mut *conn).await.unwrap();
    let url = format!("{}/{}", base.rsplit_once('/').unwrap().0, name);
    let pool = PgPoolOptions::new().max_connections(8).connect(&url).await.expect("connexion à la base de test");
    let res = pool.execute(sqlx::raw_sql(STUB)).await;
    sqlx::query("select pg_advisory_unlock(424242)").execute(&mut *conn).await.unwrap();
    res.expect("auth_stub.sql");
    for (i, m) in MIGRATIONS.iter().enumerate() {
        pool.execute(sqlx::raw_sql(m)).await.unwrap_or_else(|e| panic!("migration #{i} : {e}"));
    }
    Some(TestDb { pool, url })
}

impl TestDb {
    /// Crée un utilisateur (le déclencheur crée profil, réglages, confidentialité).
    pub async fn user(&self, email: &str) -> Uuid {
        sqlx::query_scalar("insert into auth.users (email) values ($1) returning id")
            .bind(email)
            .fetch_one(&self.pool)
            .await
            .unwrap()
    }

    pub async fn named(&self, username: &str) -> Uuid {
        let id = self.user(&format!("{username}@example.test")).await;
        self.su(&format!("set local sona.bypass_names = 'on'; update public.profiles set username = '{username}' where id = '{id}'"))
            .await;
        id
    }

    /// SQL en super-utilisateur (équivalent de l'éditeur SQL de Supabase).
    pub async fn su(&self, sql: &str) {
        let mut tx = self.pool.begin().await.unwrap();
        tx.execute(sqlx::raw_sql(sql)).await.unwrap_or_else(|e| panic!("{sql}\n{e}"));
        tx.commit().await.unwrap();
    }

    pub async fn su_scalar(&self, sql: &str) -> String {
        sqlx::query_scalar::<_, String>(&format!("select ({sql})::text")).fetch_one(&self.pool).await.unwrap()
    }

    pub async fn make_role(&self, id: Uuid, role: &str) {
        self.su(&format!("update public.profiles set role = '{role}' where id = '{id}'")).await;
    }

    pub async fn friends(&self, a: Uuid, b: Uuid) {
        self.su(&format!(
            "insert into public.friendships (requester_id, addressee_id, status, responded_at) values ('{a}','{b}','accepted', now())"
        ))
        .await;
    }

    pub async fn privacy(&self, id: Uuid, set: &str) {
        self.su(&format!("update public.privacy_settings set {set} where user_id = '{id}'")).await;
    }

    async fn begin(&self, who: Who) -> sqlx::Transaction<'_, sqlx::Postgres> {
        let mut tx = self.pool.begin().await.unwrap();
        match who {
            Who::Anon => {
                tx.execute("set local role anon").await.unwrap();
            }
            Who::User(id) => {
                tx.execute("set local role authenticated").await.unwrap();
                sqlx::query("select set_config('request.jwt.claim.sub', $1, true), set_config('request.jwt.claim.role', 'authenticated', true)")
                    .bind(id.to_string())
                    .execute(&mut *tx)
                    .await
                    .unwrap();
            }
            Who::Service => {
                tx.execute("set local role service_role").await.unwrap();
                sqlx::query("select set_config('request.jwt.claim.role', 'service_role', true)").execute(&mut *tx).await.unwrap();
            }
        }
        tx
    }

    /// Exécute une requête qui renvoie des lignes, avec les droits de `who`
    /// (RLS appliquée). Renvoie un tableau JSON, ou l'erreur SQL.
    pub async fn q(&self, who: Who, sql: &str) -> Result<Value, sqlx::Error> {
        let mut tx = self.begin(who).await;
        let wrapped = format!("select coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from ({sql}) t");
        let res: Result<Value, _> = sqlx::query_scalar(&wrapped).fetch_one(&mut *tx).await;
        match res {
            Ok(v) => {
                tx.commit().await.unwrap();
                Ok(v)
            }
            Err(e) => Err(e),
        }
    }

    /// Exécute des instructions sans résultat (appels de fonction, UPDATE…).
    pub async fn x(&self, who: Who, sql: &str) -> Result<u64, sqlx::Error> {
        let mut tx = self.begin(who).await;
        let res = tx.execute(sqlx::raw_sql(sql)).await.map(|r| r.rows_affected());
        match res {
            Ok(n) => {
                tx.commit().await.unwrap();
                Ok(n)
            }
            Err(e) => Err(e),
        }
    }

    pub async fn count(&self, who: Who, sql: &str) -> i64 {
        self.q(who, sql).await.unwrap().as_array().unwrap().len() as i64
    }
}

pub fn sqlstate(e: &sqlx::Error) -> String {
    match e {
        sqlx::Error::Database(d) => d.code().map(|c| c.to_string()).unwrap_or_default(),
        other => format!("{other}"),
    }
}

pub fn db_message(e: &sqlx::Error) -> String {
    match e {
        sqlx::Error::Database(d) => d.message().to_string(),
        other => format!("{other}"),
    }
}

#[macro_export]
macro_rules! db_or_skip {
    () => {
        match $crate::common::setup().await {
            Some(db) => db,
            None => return,
        }
    };
}

// ── HTTP ─────────────────────────────────────────────────────────────────

use axum::body::Body;
use axum::http::{Request, StatusCode};
use sona_accounts::config::Config;
use sona_accounts::state::AppState;
use tower::ServiceExt;

pub fn token_for(secret: &str, sub: Uuid, extra: serde_json::Value) -> String {
    use jsonwebtoken::{encode, EncodingKey, Header};
    let exp = (chrono::Utc::now().timestamp() + 3600) as u64;
    let mut claims = json!({ "sub": sub.to_string(), "aud": "authenticated", "role": "authenticated", "exp": exp });
    if let (Some(c), Some(e)) = (claims.as_object_mut(), extra.as_object()) {
        for (k, v) in e {
            c.insert(k.clone(), v.clone());
        }
    }
    encode(&Header::new(jsonwebtoken::Algorithm::HS256), &claims, &EncodingKey::from_secret(secret.as_bytes())).unwrap()
}

use serde_json::json;

pub struct Api {
    pub state: AppState,
    pub db: TestDb,
}

impl Api {
    pub async fn new() -> Option<Api> {
        Self::with(|_, _| {}).await
    }

    pub async fn with(tweak: impl FnOnce(&mut Config, &mut AppState)) -> Option<Api> {
        let db = setup().await?;
        let mut cfg = Config::for_tests(&db.url);
        // La base de test ne parle pas à Supabase.
        let mut dummy = AppState::new(cfg.clone(), db.pool.clone());
        tweak(&mut cfg, &mut dummy);
        let mut state = AppState::new(cfg, db.pool.clone());
        state.lastfm_base = dummy.lastfm_base.clone();
        Some(Api { state, db })
    }

    pub fn token(&self, id: Uuid) -> String {
        token_for(self.state.cfg.jwt_secret.as_deref().unwrap(), id, json!({}))
    }

    pub async fn call(&self, method: &str, path: &str, bearer: Option<&str>, body: Option<serde_json::Value>) -> (StatusCode, serde_json::Value) {
        self.call_with(method, path, &[("authorization", bearer.map(|b| format!("Bearer {b}")).unwrap_or_default())], body).await
    }

    pub async fn call_with(&self, method: &str, path: &str, headers: &[(&str, String)], body: Option<serde_json::Value>) -> (StatusCode, serde_json::Value) {
        let mut h = headers.to_vec();
        if body.is_some() {
            h.push(("content-type", "application/json".to_string()));
        }
        self.call_raw(method, path, &h, body.map(|b| b.to_string()).unwrap_or_default()).await
    }

    /// Corps envoyé tel quel (signatures de webhook calculées sur les octets).
    pub async fn call_raw(&self, method: &str, path: &str, headers: &[(&str, String)], body: String) -> (StatusCode, serde_json::Value) {
        let mut req = Request::builder().method(method).uri(path);
        for (k, v) in headers {
            if !v.is_empty() {
                req = req.header(*k, v);
            }
        }
        let resp = sona_accounts::routes::router(self.state.clone()).oneshot(req.body(Body::from(body)).unwrap()).await.unwrap();
        let status = resp.status();
        let bytes = http_body_util::BodyExt::collect(resp.into_body()).await.unwrap().to_bytes();
        (status, serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null))
    }

    pub async fn internal(&self, method: &str, path: &str, body: Option<serde_json::Value>) -> (StatusCode, serde_json::Value) {
        self.call_with(method, path, &[("x-sona-internal", self.state.cfg.internal_secret.clone().unwrap())], body).await
    }
}

/// Faux serveur HTTP (Last.fm, serveur musique, Discord, GoTrue) : enregistre
/// chaque requête reçue et répond avec ce que dit `handler`.
pub mod mock {
    use axum::body::Bytes;
    use axum::extract::State;
    use axum::http::{HeaderMap, Method, Uri};
    use axum::Router;
    use std::sync::{Arc, Mutex};

    #[derive(Clone, Debug)]
    pub struct Seen {
        pub method: String,
        pub uri: String,
        pub headers: HeaderMap,
        pub body: String,
    }

    type Handler = Arc<dyn Fn(&Seen) -> (u16, String) + Send + Sync>;

    pub struct Server {
        pub url: String,
        pub seen: Arc<Mutex<Vec<Seen>>>,
    }

    pub async fn start(handler: impl Fn(&Seen) -> (u16, String) + Send + Sync + 'static) -> Server {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let h: Handler = Arc::new(handler);
        let state = (seen.clone(), h);
        async fn any(State((seen, h)): State<(Arc<Mutex<Vec<Seen>>>, Handler)>, method: Method, uri: Uri, headers: HeaderMap, body: Bytes) -> (axum::http::StatusCode, String) {
            let s = Seen { method: method.to_string(), uri: uri.to_string(), headers, body: String::from_utf8_lossy(&body).to_string() };
            let (code, out) = h(&s);
            seen.lock().unwrap().push(s);
            (axum::http::StatusCode::from_u16(code).unwrap(), out)
        }
        let app = Router::new().fallback(any).with_state(state);
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        Server { url, seen }
    }

    impl Server {
        pub fn requests(&self) -> Vec<Seen> {
            self.seen.lock().unwrap().clone()
        }
    }
}

/// Valeur d'un champ d'un corps `application/x-www-form-urlencoded`.
pub fn form(body: &str) -> std::collections::BTreeMap<String, String> {
    url::form_urlencoded::parse(body.as_bytes()).into_owned().collect()
}
