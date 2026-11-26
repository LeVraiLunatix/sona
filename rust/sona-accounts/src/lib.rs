//! Sona : comptes, social, administration et modération.
//!
//! Service Rust qui remplace les Edge Functions Supabase du cahier des charges
//! (le secret Last.fm, les actions d'admin et l'envoi d'alertes ne doivent jamais
//! atteindre un client). Les autres crates du serveur Sona (musique) peuvent
//! réutiliser `auth` et `sessions`.

pub mod config;
pub mod crypto;
pub mod error;
pub mod jwt;
pub mod lastfm_sig;
pub mod ratelimit;
pub mod redirect;
pub mod sessions;
pub mod webhook;
