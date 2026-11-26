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
