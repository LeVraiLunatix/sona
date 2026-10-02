//! `sona-iphone` : installe Sona sur l'iPhone depuis le PC, comme CordLauncher.
//!
//! Connexion au compte Apple (2FA), enregistrement de l'iPhone, signature de
//! l'IPA avec le compte de l'utilisateur, envoi par câble ou en Wi-Fi, suivi
//! de l'expiration pour renouveler. Le moteur est `isideload`.
//!
//! L'app Electron lance ce programme et lui parle en JSON, une ligne par
//! message :
//!   → `{"id": 1, "cmd": "login", "email": "…", "password": "…", "remember": true}`
//!   ← `{"id": 1, "ok": true, "result": {…}}` ou `{"id": 1, "ok": false, "error": "…"}`
//!   ← évènements sans `id` : `{"event": "2fa", …}`, `{"event": "progress", …}`.
//! Les commandes tournent en parallèle : la réponse à la 2FA arrive pendant
//! que la connexion l'attend.

mod registry;
mod sideload;
mod wifi;

use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;

use serde::Deserialize;
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, BufReader};

/// Libellé présenté à l'iPhone et nom de machine des certificats Apple.
pub const LABEL: &str = "Sona";

static OUT: Mutex<()> = Mutex::new(());

/// Écrit un message pour l'app (une ligne JSON).
pub fn send(value: Value) {
    let _guard = OUT.lock().unwrap_or_else(|e| e.into_inner());
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{value}");
    let _ = out.flush();
}

/// Évènement vers l'app (2FA, progression…).
pub fn emit(event: &str, payload: Value) {
    let mut message = json!({ "event": event });
    if let (Some(m), Value::Object(p)) = (message.as_object_mut(), payload) {
        m.extend(p);
    }
    send(message);
}

/// Dossier des données iPhone : celui que donne l'app (`SONA_IPHONE_DIR`),
/// sinon `%LOCALAPPDATA%\Sona\iphone`.
pub fn data_dir() -> Option<PathBuf> {
    if let Some(dir) = std::env::var_os("SONA_IPHONE_DIR") {
        return Some(PathBuf::from(dir));
    }
    let base = std::env::var_os("LOCALAPPDATA").or_else(|| std::env::var_os("HOME"))?;
    Some(PathBuf::from(base).join("Sona").join("iphone"))
}

pub fn unix_now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

#[derive(Deserialize)]
struct Request {
    id: u64,
    #[serde(flatten)]
    command: sideload::Command,
}

#[tokio::main]
async fn main() {
    if let Err(e) = isideload::init() {
        eprintln!("[iphone] rapports d'erreur isideload indisponibles : {e}");
    }
    if std::env::args().any(|a| a == "--version") {
        println!("{}", env!("CARGO_PKG_VERSION"));
        return;
    }
    emit("ready", json!({ "version": env!("CARGO_PKG_VERSION") }));
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    // L'app ferme l'entrée standard en quittant : on s'arrête avec elle.
    while let Ok(Some(line)) = lines.next_line().await {
        if line.trim().is_empty() {
            continue;
        }
        let request: Request = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(e) => {
                let id = serde_json::from_str::<Value>(&line).ok().and_then(|v| v.get("id").and_then(Value::as_u64));
                send(json!({ "id": id, "ok": false, "error": format!("Commande illisible : {e}") }));
                continue;
            }
        };
        tokio::spawn(async move {
            let id = request.id;
            match sideload::run(request.command).await {
                Ok(result) => send(json!({ "id": id, "ok": true, "result": result })),
                Err(error) => send(json!({ "id": id, "ok": false, "error": error })),
            }
        });
    }
}
