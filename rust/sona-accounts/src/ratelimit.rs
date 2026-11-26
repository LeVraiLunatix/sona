//! Limites par clé, comptées en base (`private.rate_limits`) : valables pour
//! toutes les instances du service et partagées avec les fonctions SQL.

use crate::error::{AppError, Result};
use sqlx::PgPool;

pub async fn check(pool: &PgPool, key: &str, max: i32, window_seconds: i32) -> Result<()> {
    let allowed: bool = sqlx::query_scalar("select public.rate_limit_check($1, $2, $3)")
        .bind(key)
        .bind(max)
        .bind(window_seconds)
        .fetch_one(pool)
        .await?;
    if allowed {
        Ok(())
    } else {
        Err(AppError::RateLimited)
    }
}
