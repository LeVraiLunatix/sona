//! Sona : comptes, social, administration et modération.
//!
//! Service Rust qui remplace les Edge Functions Supabase du cahier des charges
//! (le secret Last.fm, les actions d'admin et l'envoi d'alertes ne doivent jamais
//! atteindre un client). Le serveur musique peut réutiliser `auth` et `sessions`.

pub mod account;
pub mod admin;
pub mod alerts;
pub mod auth;
pub mod config;
pub mod crypto;
pub mod error;
pub mod hooks;
pub mod internal;
pub mod jwt;
pub mod lastfm;
pub mod lastfm_sig;
pub mod maintenance;
pub mod music;
pub mod passkey;
pub mod ratelimit;
pub mod redirect;
pub mod routes;
pub mod sessions;
pub mod state;
pub mod webhook;
