//! Compte Apple, iPhone branchés et installation : le moteur de CordLauncher
//! (`sideload.rs`), sans Tauri.
//!
//! La mécanique vient d'`isideload` :
//!   connexion Apple (SRP + 2FA)  →  session développeur (équipe, certificat,
//!   appareil, identifiants d'app)  →  re-signature de l'IPA  →  envoi par
//!   usbmuxd (service Apple Mobile Device, installé avec iTunes) ou en Wi-Fi.
//!
//! Limites d'un compte Apple gratuit, qu'on ne contourne pas : app valable
//! 7 jours, 3 apps actives, 10 identifiants d'app par semaine.
//!
//! Choix (repris de CordLauncher) :
//!  - certificats pleins → on ne révoque QUE ceux créés par Sona (machine
//!    « Sona »), jamais ceux d'AltStore, Sideloadly ou CordLauncher ;
//!  - chaque opération isideload tourne sur son propre fil avec son propre
//!    runtime : ses futures ne sont pas garanties `Send` ;
//!  - le mot de passe n'est gardé (coffre Windows) que si l'utilisateur le
//!    demande : il sert à re-signer Sona chaque semaine sans rien redemander.

use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use futures_util::StreamExt;
use idevice::lockdown::LockdownClient;
use idevice::provider::IdeviceProvider;
use idevice::usbmuxd::{Connection, UsbmuxdAddr, UsbmuxdConnection};
use idevice::IdeviceService;
use isideload::auth::apple_account::{AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse};
use isideload::dev::developer_session::DeveloperSession;
use isideload::dev::devices::DevicesApi;
use isideload::sideload::builder::MaxCertsBehavior;
use isideload::sideload::{SideloaderBuilder, TeamSelection};
use isideload::util::device::IdeviceInfo;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;
use tokio::sync::oneshot;

use crate::{data_dir, emit, registry, unix_now, wifi, LABEL};

const KEYRING_SERVICE: &str = "Sona Apple ID";

// ── Commandes ───────────────────────────────────────────────────────────────

#[derive(Deserialize)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum Command {
    Status,
    Login { email: String, password: String, remember: bool },
    TwoFactor { response: TwoFactorCallbackResponse },
    Switch { email: String },
    Forget { email: String },
    ResetDevice,
    Devices,
    SetWifi { udid: String, enabled: bool },
    #[serde(rename_all = "camelCase")]
    Sideload {
        /// Identifiant de l'app dans Sona (`sona`) ; `id` est celui du message.
        app: String,
        name: String,
        ipa_url: Option<String>,
        ipa_path: Option<String>,
        udid: String,
        device_name: Option<String>,
    },
    Apps,
    AppForget { app: String, udid: String },
    DeviceBundles { udid: String },
}

fn to_json<T: Serialize>(value: &T) -> Value {
    serde_json::to_value(value).unwrap_or(Value::Null)
}

pub async fn run(command: Command) -> Result<Value, String> {
    match command {
        Command::Status => Ok(to_json(&status())),
        Command::Login { email, password, remember } => apple_login(email, password, remember).await.map(|s| to_json(&s)),
        Command::TwoFactor { response } => two_factor_respond(response).map(|_| Value::Null),
        Command::Switch { email } => apple_switch(email).map(|s| to_json(&s)),
        Command::Forget { email } => apple_forget(email).await.map(|s| to_json(&s)),
        Command::ResetDevice => apple_reset_device().await.map(|_| Value::Null),
        Command::Devices => iphone_list().await.map(|d| to_json(&d)),
        Command::SetWifi { udid, enabled } => iphone_set_wifi(udid, enabled).await.map(|_| Value::Null),
        Command::Sideload { app, name, ipa_url, ipa_path, udid, device_name } => {
            iphone_sideload(app, name, ipa_url, ipa_path, udid, device_name).await.map(|_| Value::Null)
        }
        Command::Apps => Ok(to_json(&registry::list())),
        Command::AppForget { app, udid } => registry::forget(&app, &udid).map(|_| Value::Null),
        Command::DeviceBundles { udid } => registry::device_bundles(udid).await.map(|b| to_json(&b)),
    }
}

// ── État ────────────────────────────────────────────────────────────────────

#[derive(Default)]
struct AppleState {
    /// Sessions ouvertes, par identifiant (en minuscules). Le verrou sert aussi
    /// de garde « une seule opération Apple à la fois ».
    sessions: tokio::sync::Mutex<HashMap<String, AppleAccount>>,
    /// Copie des clés de `sessions`, lisible même pendant une opération.
    connected: Mutex<HashSet<String>>,
    /// Réponse attendue par la 2FA en cours.
    pending_2fa: Mutex<Option<oneshot::Sender<TwoFactorCallbackResponse>>>,
}

fn state() -> &'static AppleState {
    static STATE: OnceLock<AppleState> = OnceLock::new();
    STATE.get_or_init(AppleState::default)
}

const BUSY: &str = "Une opération Apple est déjà en cours.";

// ── Profils Apple ───────────────────────────────────────────────────────────
// Plusieurs identifiants Apple, dont un actif (celui qui signe Sona). La liste
// (sans secret) vit dans `apple-profiles.json` ; chaque mot de passe mémorisé
// a sa propre entrée du coffre Windows.

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
struct ProfileMeta {
    email: String,
    added_at: u64,
    last_used_at: Option<u64>,
}

#[derive(Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct ProfileIndex {
    active: Option<String>,
    profiles: Vec<ProfileMeta>,
}

impl ProfileIndex {
    fn upsert(&mut self, email: &str) {
        let now = unix_now();
        match self.profiles.iter_mut().find(|p| profile_key(&p.email) == profile_key(email)) {
            Some(p) => {
                p.email = email.to_string();
                p.last_used_at = Some(now);
            }
            None => self.profiles.push(ProfileMeta { email: email.to_string(), added_at: now, last_used_at: Some(now) }),
        }
        self.active = Some(email.to_string());
    }
    fn find(&self, email: &str) -> Option<&ProfileMeta> {
        self.profiles.iter().find(|p| profile_key(&p.email) == profile_key(email))
    }
}

fn profile_key(email: &str) -> String {
    email.trim().to_lowercase()
}

fn password_entry(email: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(KEYRING_SERVICE, &profile_key(email)).map_err(|e| {
        log_error(&format!("coffre : {e}"));
        "Le coffre de Windows est inaccessible : impossible de garder le mot de passe Apple.".to_string()
    })
}

fn saved_password(email: &str) -> Option<String> {
    password_entry(email).ok()?.get_password().ok()
}

fn forget_password(email: &str) {
    if let Ok(entry) = password_entry(email) {
        let _ = entry.delete_credential();
    }
}

fn load_profiles() -> ProfileIndex {
    data_dir()
        .map(|d| d.join("apple-profiles.json"))
        .and_then(|p| std::fs::read(p).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn save_profiles(index: &ProfileIndex) -> Result<(), String> {
    let dir = data_dir().ok_or("Dossier de Sona introuvable.")?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let json = serde_json::to_vec_pretty(index).map_err(|e| e.to_string())?;
    std::fs::write(dir.join("apple-profiles.json"), json).map_err(|e| {
        log_error(&format!("profils : {e}"));
        "Impossible d’enregistrer tes comptes Apple sur ce PC.".to_string()
    })
}

// ── Erreurs lisibles ────────────────────────────────────────────────────────

/// Erreur isideload lisible : les rapports sont des arbres (message,
/// `├ fichier.rs:ligne`…) ; on garde la chaîne des messages, sans décoration.
/// Le rapport complet part dans `logs/iphone.log`.
pub fn short_error(e: impl std::fmt::Display + std::fmt::Debug) -> String {
    let full = e.to_string();
    log_error(&format!("{e:?}"));
    let mut messages: Vec<String> = Vec::new();
    for line in full.lines() {
        let text = line.trim_start_matches(|c: char| "│├╰└─●•┬┴┼ \t".contains(c)).trim();
        let location = text.contains(".rs:") && !text.contains(' ');
        if text.is_empty() || location || messages.iter().any(|m| m == text) {
            continue;
        }
        messages.push(text.to_string());
    }
    if messages.is_empty() {
        return humanize(full.trim());
    }
    messages.truncate(6);
    humanize(&messages.join(" → "))
}

/// Traduit les erreurs techniques (isideload, idevice, réseau, Apple) en une
/// phrase qui dit quoi faire.
pub fn humanize(chain: &str) -> String {
    let lower = chain.to_lowercase();
    let has = |needles: &[&str]| needles.iter().any(|n| lower.contains(n));
    let message = if has(&["429", "too many requests"]) {
        "Apple limite les tentatives depuis ce PC. Patiente quelques minutes avant de réessayer."
    } else if has(&["-22406", "correct password"]) {
        "Mot de passe Apple incorrect. Vérifie-le et réessaie."
    } else if has(&["additional authentication", "2fa", "two-factor", "trusted device", "sms"]) {
        "La vérification en deux étapes d’Apple n’a pas abouti. Réessaie et saisis le nouveau code."
    } else if has(&["anisette"]) {
        "Impossible de préparer la connexion à Apple. Vérifie ta connexion Internet, puis réessaie."
    } else if has(&["pairing file", "pair record", "invalidhostid", "passwordprotected", "not paired", "pairingdialog"]) {
        "L’iPhone ne fait pas encore confiance à ce PC : déverrouille-le et touche « Se fier »."
    } else if has(&["developer mode", "developermode"]) {
        "Active le mode développeur sur l’iPhone (Réglages › Confidentialité et sécurité › Mode développeur), puis réessaie."
    } else if has(&["maximum number of app", "app id limit", "maximum app id"]) {
        "Limite d’Apple atteinte : un compte gratuit peut créer 10 identifiants d’app par semaine. Réessaie dans quelques jours, ou utilise un autre compte Apple."
    } else if has(&["maximum number of installed apps", "free developer profile"]) {
        "Ton iPhone a déjà 3 apps installées avec un compte Apple gratuit : iOS n’en accepte pas une 4e. Supprime l’une d’elles de l’iPhone (ou utilise un autre compte Apple), puis réessaie."
    } else if has(&["certificate"]) && has(&["max", "limit", "too many"]) {
        "Ton compte Apple a déjà le maximum de certificats actifs, et ils ne viennent pas de Sona (AltStore, Sideloadly, CordLauncher…). Révoque-les depuis ces outils, ou attends leur expiration."
    } else if has(&["device lockdown", "socket io", "early eof", "connection refused", "connection reset", "no such device", "device not found", "broken pipe"]) {
        "Impossible de joindre l’iPhone. Déverrouille-le et vérifie le câble, ou qu’il est sur le même Wi-Fi que ce PC."
    } else if has(&["extract application archive", "open application archive", "invalid zip", "info.plist"]) {
        "Le fichier de l’app semble abîmé. Réessaie : Sona le retéléchargera."
    } else if has(&["install app on device", "installation_proxy", "applicationverificationfailed"]) {
        "L’iPhone a refusé l’installation. Déverrouille-le, vérifie qu’il reste de la place, puis réessaie."
    } else if has(&["error sending request", "dns error", "failed to lookup", "timed out", "connect error", "tls handshake"]) {
        "Apple est injoignable pour le moment. Vérifie ta connexion Internet, puis réessaie."
    } else if has(&["log in to apple id", "login again", "srp"]) {
        "Connexion au compte Apple impossible. Vérifie l’adresse et le mot de passe, puis réessaie."
    } else if has(&["developer request", "list developer", "provisioning profile", "app token", "url bag", "grandslam"]) {
        "Apple n’a pas répondu comme prévu. Réessaie dans un instant."
    } else if chain.is_ascii() {
        "Quelque chose s’est mal passé avec l’iPhone. Réessaie ; si ça recommence, le détail est dans le journal (Réglages › iPhone)."
    } else {
        return chain.to_string();
    };
    message.to_string()
}

pub fn log_error(detail: &str) {
    eprintln!("[iphone] {detail}");
    let Some(dir) = data_dir().map(|d| d.join("logs")) else { return };
    if std::fs::create_dir_all(&dir).is_err() {
        return;
    }
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("iphone.log")) {
        use std::io::Write;
        let _ = writeln!(file, "── {} ──\n{detail}\n", unix_now());
    }
}

/// Exécute un futur non-`Send` sur un fil dédié et rend son résultat.
pub async fn on_own_thread<F, Fut, T>(make: F) -> Result<T, String>
where
    F: FnOnce() -> Fut + Send + 'static,
    Fut: Future<Output = Result<T, String>> + 'static,
    T: Send + 'static,
{
    let (tx, rx) = oneshot::channel();
    std::thread::spawn(move || {
        let result = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| e.to_string())
            .and_then(|rt| rt.block_on(make()));
        let _ = tx.send(result);
    });
    rx.await.unwrap_or_else(|_| Err("L'opération iPhone s'est interrompue.".into()))
}

// ── Compte Apple ────────────────────────────────────────────────────────────

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppleProfile {
    email: String,
    /// Compte qui signe Sona.
    active: bool,
    /// Session ouverte pendant cette exécution.
    connected: bool,
    /// Mot de passe gardé dans le coffre Windows (renouvellement automatique).
    remembered: bool,
    added_at: u64,
    last_used_at: Option<u64>,
    /// Secondes avant de pouvoir retenter (pause après des refus d'Apple).
    paused_for: Option<u64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppleStatus {
    active: Option<String>,
    profiles: Vec<AppleProfile>,
    /// Une opération Apple est en cours (connexion, installation).
    busy: bool,
}

fn status() -> AppleStatus {
    status_of(&load_profiles())
}

fn status_of(index: &ProfileIndex) -> AppleStatus {
    let connected = state().connected.lock().unwrap().clone();
    let active = index.active.as_deref().map(profile_key);
    let mut profiles: Vec<AppleProfile> = index
        .profiles
        .iter()
        .map(|p| AppleProfile {
            email: p.email.clone(),
            active: active.as_deref() == Some(profile_key(&p.email).as_str()),
            connected: connected.contains(&profile_key(&p.email)),
            remembered: saved_password(&p.email).is_some(),
            added_at: p.added_at,
            last_used_at: p.last_used_at,
            paused_for: apple_cooldown_left(&p.email),
        })
        .collect();
    profiles.sort_by_key(|p| (!p.active, std::cmp::Reverse(p.last_used_at.unwrap_or(p.added_at))));
    AppleStatus { active: index.active.clone(), profiles, busy: state().sessions.try_lock().is_err() }
}

fn apple_switch(email: String) -> Result<AppleStatus, String> {
    let mut index = load_profiles();
    let email = index.find(&email).map(|p| p.email.clone()).ok_or("Ce compte Apple n'est plus enregistré.")?;
    index.upsert(&email);
    save_profiles(&index)?;
    Ok(status_of(&index))
}

async fn apple_forget(email: String) -> Result<AppleStatus, String> {
    let mut sessions = state().sessions.try_lock().map_err(|_| BUSY)?;
    let key = profile_key(&email);
    sessions.remove(&key);
    state().connected.lock().unwrap().remove(&key);
    forget_password(&email);
    let mut index = load_profiles();
    index.profiles.retain(|p| profile_key(&p.email) != key);
    if index.active.as_deref().map(profile_key).as_deref() == Some(key.as_str()) {
        index.active = index.profiles.iter().max_by_key(|p| p.last_used_at.unwrap_or(p.added_at)).map(|p| p.email.clone());
    }
    save_profiles(&index)?;
    drop(sessions);
    Ok(status_of(&index))
}

/// Connexion, avec une pause de 10 minutes si Apple refuse encore en rafale (429).
async fn login(email: String, password: String) -> Result<AppleAccount, String> {
    if let Some(left) = apple_cooldown_left(&email) {
        return Err(format!(
            "Apple bloque encore les connexions à ce compte (trop de tentatives). Réessaie dans {}, sans relancer d'ici là.",
            duration_fr(left)
        ));
    }
    let result = login_attempt(email.clone(), password).await;
    if result.is_ok() {
        emit("signed-in", json!({ "email": email }));
    }
    if let Err(message) = &result {
        if message.contains("429") || message.contains("Too Many Requests") || message.starts_with("Apple limite les tentatives") {
            let seconds = 10 * 60;
            set_apple_cooldown(&email, seconds);
            return Err(format!(
                "Apple refuse les connexions pour le moment (trop de tentatives). Sona a déjà réessayé plusieurs fois : réessaie dans {}.",
                duration_fr(seconds)
            ));
        }
    }
    result
}

fn duration_fr(seconds: u64) -> String {
    let minutes = seconds / 60 + 1;
    if minutes < 90 {
        format!("{minutes} min")
    } else {
        format!("{} h", (minutes + 30) / 60)
    }
}

fn apple_cooldown_file(email: &str) -> Option<PathBuf> {
    let id: String = email.trim().to_lowercase().chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '_' }).collect();
    Some(data_dir()?.join(format!("apple-cooldown-{id}")))
}
fn apple_cooldown_left(email: &str) -> Option<u64> {
    let until: u64 = std::fs::read_to_string(apple_cooldown_file(email)?).ok()?.trim().parse().ok()?;
    until.checked_sub(unix_now()).filter(|left| *left > 0)
}
fn set_apple_cooldown(email: &str, seconds: u64) {
    let Some(file) = apple_cooldown_file(email) else { return };
    let until = unix_now() + seconds;
    let written = std::fs::create_dir_all(file.parent().unwrap()).and_then(|_| std::fs::write(&file, until.to_string()));
    log_error(&format!("Apple 429 : pause jusqu'à {until} ({seconds} s) → {written:?}"));
}

async fn login_attempt(email: String, password: String) -> Result<AppleAccount, String> {
    on_own_thread(move || async move {
        let for_callback = email.clone();
        isideload::auth::builder::AppleAccountBuilder::new(&email)
            .login(&password, move |params: TwoFactorCallbackParams| {
                let email = for_callback.clone();
                async move {
                    let (tx, rx) = oneshot::channel();
                    *state().pending_2fa.lock().unwrap() = Some(tx);
                    let mut payload = serde_json::to_value(&params).unwrap_or(Value::Null);
                    if let Some(map) = payload.as_object_mut() {
                        map.insert("email".into(), json!(email));
                        map.insert("expiresIn".into(), json!(180));
                    }
                    emit("2fa", payload);
                    let response = tokio::time::timeout(Duration::from_secs(180), rx).await;
                    state().pending_2fa.lock().unwrap().take();
                    Ok(response.ok().and_then(Result::ok).unwrap_or(TwoFactorCallbackResponse::Abort))
                }
            })
            .await
            .map_err(short_error)
    })
    .await
}

async fn apple_login(email: String, password: String, remember: bool) -> Result<AppleStatus, String> {
    let mut sessions = state().sessions.try_lock().map_err(|_| BUSY)?;
    let email = email.trim().to_string();
    if email.is_empty() || password.is_empty() {
        return Err("Entre l'identifiant et le mot de passe du compte Apple.".into());
    }
    let account = login(email.clone(), password.clone()).await?;
    sessions.insert(profile_key(&email), account);
    state().connected.lock().unwrap().insert(profile_key(&email));
    if remember {
        password_entry(&email)?.set_password(&password).map_err(|e| {
            log_error(&format!("coffre : {e}"));
            "Le coffre de Windows est inaccessible : impossible de garder le mot de passe Apple.".to_string()
        })?;
    } else {
        forget_password(&email);
    }
    let mut index = load_profiles();
    index.upsert(&email);
    save_profiles(&index)?;
    drop(sessions);
    Ok(status_of(&index))
}

fn two_factor_respond(response: TwoFactorCallbackResponse) -> Result<(), String> {
    let sender = state().pending_2fa.lock().unwrap().take().ok_or("Aucune vérification en attente.")?;
    sender.send(response).map_err(|_| "La vérification a expiré.".to_string())
}

/// Oublie l'« appareil » présenté à Apple (identité anisette gardée par
/// isideload dans le coffre Windows) et lève les pauses.
async fn apple_reset_device() -> Result<(), String> {
    let mut sessions = state().sessions.try_lock().map_err(|_| BUSY)?;
    sessions.clear();
    state().connected.lock().unwrap().clear();
    match keyring::Entry::new("isideload", "anisette_state").and_then(|e| e.delete_credential()) {
        Ok(()) | Err(keyring::Error::NoEntry) => {}
        Err(e) => {
            log_error(&format!("coffre : {e}"));
            return Err("Le coffre de Windows est inaccessible.".into());
        }
    }
    for entry in data_dir().and_then(|d| std::fs::read_dir(d).ok()).into_iter().flatten().flatten() {
        if entry.file_name().to_string_lossy().starts_with("apple-cooldown") {
            let _ = std::fs::remove_file(entry.path());
        }
    }
    log_error("Appareil Apple réinitialisé (identité anisette supprimée)");
    Ok(())
}

// ── iPhone branchés ─────────────────────────────────────────────────────────

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct IphoneDevice {
    udid: String,
    name: Option<String>,
    ios_version: Option<String>,
    /// "usb", "wifi" ou "offline" (vu par câble, introuvable en Wi-Fi).
    connection: &'static str,
    /// Faux tant que l'iPhone n'a pas répondu « Se fier à cet ordinateur ».
    trusted: bool,
    /// Connexion Wi-Fi avec ce PC activée sur l'iPhone.
    wifi: Option<bool>,
}

const WIRELESS_DOMAIN: &str = "com.apple.mobile.wireless_lockdown";
const NO_SERVICE: &str = "Service Apple Mobile Device introuvable : installe iTunes ou « Appareils Apple » depuis le Microsoft Store.";

async fn device_details(provider: &impl IdeviceProvider) -> Option<(String, Option<String>, Option<bool>)> {
    let mut lockdown = LockdownClient::connect(provider).await.ok()?;
    let pairing = provider.get_pairing_file().await.ok()?;
    lockdown.start_session(&pairing).await.ok()?;
    let name = lockdown.get_value(Some("DeviceName"), None).await.ok()?.as_string()?.to_string();
    let version = lockdown.get_value(Some("ProductVersion"), None).await.ok().and_then(|v| v.as_string().map(str::to_string));
    let wifi = lockdown
        .get_value(Some("EnableWifiConnections"), Some(WIRELESS_DOMAIN))
        .await
        .ok()
        .and_then(|v| v.as_boolean());
    Some((name, version, wifi))
}

/// Active (ou coupe) la connexion Wi-Fi de l'iPhone avec ce PC.
async fn iphone_set_wifi(udid: String, enabled: bool) -> Result<(), String> {
    on_own_thread(move || async move {
        let mut mux = UsbmuxdConnection::default().await.map_err(|_| NO_SERVICE.to_string())?;
        let device = mux.get_device(&udid).await.map_err(|_| "Branche l’iPhone avec un câble pour changer ce réglage.".to_string())?;
        let provider = device.to_provider(UsbmuxdAddr::default(), LABEL);
        let mut lockdown = LockdownClient::connect(&provider).await.map_err(short_error)?;
        let pairing = provider.get_pairing_file().await.map_err(|_| "Déverrouille l’iPhone et touche « Se fier » d’abord.".to_string())?;
        lockdown.start_session(&pairing).await.map_err(short_error)?;
        lockdown
            .set_value("EnableWifiConnections", plist::Value::Boolean(enabled), Some(WIRELESS_DOMAIN))
            .await
            .map_err(short_error)
    })
    .await
}

async fn iphone_list() -> Result<Vec<IphoneDevice>, String> {
    on_own_thread(|| async {
        let mut mux = UsbmuxdConnection::default().await.map_err(|_| NO_SERVICE.to_string())?;
        let devices = mux.get_devices().await.map_err(short_error)?;
        let mut out: Vec<IphoneDevice> = Vec::new();
        // Par câble uniquement : les iPhone « réseau » du service d'Apple
        // échouent souvent à se connecter ; le Wi-Fi passe par `wifi`.
        for d in devices.iter().filter(|d| matches!(d.connection_type, Connection::Usb)) {
            if out.iter().any(|x| x.udid == d.udid) {
                continue;
            }
            let provider = d.to_provider(UsbmuxdAddr::default(), LABEL);
            let details = device_details(&provider).await;
            if let (Some((name, _, _)), Ok(pairing)) = (details.as_ref(), provider.get_pairing_file().await) {
                wifi::remember(&d.udid, Some(name), &pairing.wifi_mac_address);
            }
            out.push(IphoneDevice {
                udid: d.udid.clone(),
                trusted: details.is_some(),
                name: details.as_ref().map(|(n, _, _)| n.clone()),
                wifi: details.as_ref().and_then(|(_, _, w)| *w),
                ios_version: details.and_then(|(_, v, _)| v),
                connection: "usb",
            });
        }
        // iPhone déjà vus par câble, débranchés : on les cherche en Wi-Fi.
        let missing: Vec<_> = wifi::known().into_iter().filter(|k| !out.iter().any(|x| x.udid == k.udid)).collect();
        for k in &missing {
            let Some(provider) = wifi::wifi_provider(&mut mux, k).await else { continue };
            if let Ok(Some((name, version, _))) = tokio::time::timeout(Duration::from_secs(6), device_details(&provider)).await {
                out.push(IphoneDevice { udid: k.udid.clone(), trusted: true, name: Some(name), wifi: Some(true), ios_version: version, connection: "wifi" });
            }
        }
        let offline: Vec<_> = missing.iter().filter(|k| !out.iter().any(|x| x.udid == k.udid)).collect();
        for k in offline {
            out.push(IphoneDevice { udid: k.udid.clone(), trusted: false, name: k.name.clone(), wifi: Some(true), ios_version: None, connection: "offline" });
        }
        Ok(out)
    })
    .await
}

// ── Installation ────────────────────────────────────────────────────────────

fn progress(id: &str, phase: &str, value: f32) {
    emit("progress", json!({ "id": id, "phase": phase, "progress": value }));
}

/// Installe Sona sur l'iPhone, depuis `ipa_url` (téléchargée) ou `ipa_path`
/// (copie gardée pour renouveler, ou fichier choisi).
async fn iphone_sideload(
    id: String,
    name: String,
    ipa_url: Option<String>,
    ipa_path: Option<String>,
    udid: String,
    device_name: Option<String>,
) -> Result<(), String> {
    if id.is_empty() || !id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        return Err("Identifiant d'app invalide.".into());
    }
    // Compte actif : sa session ouverte, sinon reconnexion avec le mot de passe mémorisé.
    let mut sessions = state().sessions.try_lock().map_err(|_| BUSY)?;
    let mut index = load_profiles();
    let email = index.active.clone().ok_or("Connecte d'abord un compte Apple.")?;
    let key = profile_key(&email);
    if !sessions.contains_key(&key) {
        progress(&id, "account", -1.0);
        let password = saved_password(&email).ok_or_else(|| format!("Reconnecte {email} : son mot de passe n'est pas mémorisé sur ce PC."))?;
        sessions.insert(key.clone(), login(email.clone(), password).await?);
        state().connected.lock().unwrap().insert(key.clone());
    }
    index.upsert(&email);
    let _ = save_profiles(&index);

    // 1. L'IPA : fichier local, sinon téléchargement (supprimé après coup).
    let (ipa, remove_after) = match (ipa_path, ipa_url) {
        (Some(path), _) => {
            let p = PathBuf::from(&path);
            if !p.is_file() || !path.to_ascii_lowercase().ends_with(".ipa") {
                return Err("Fichier .ipa introuvable.".into());
            }
            (p, false)
        }
        (None, Some(url)) => {
            let dest = std::env::temp_dir().join("Sona").join(format!("{id}.ipa"));
            std::fs::create_dir_all(dest.parent().unwrap()).map_err(|e| e.to_string())?;
            let id2 = id.clone();
            download(&url, &dest, move |r, t| progress(&id2, "downloading", if t > 0 { r as f32 / t as f32 } else { -1.0 })).await?;
            (dest, true)
        }
        (None, None) => return Err("Aucune app à installer.".into()),
    };

    // 2 + 3. Signature et envoi, sur un fil dédié. Le compte y part et revient.
    let account = sessions.remove(&key).expect("session ouverte ci-dessus");
    let (id2, ipa2, email2, udid2) = (id.clone(), ipa.clone(), email.clone(), udid.clone());
    let outcome = on_own_thread(move || async move { Ok(sign_and_install(&id2, account, email2, ipa2, udid2).await) }).await;
    let result = match outcome {
        Ok((result, Some(account))) => {
            sessions.insert(key, account);
            result
        }
        Ok((result, None)) => {
            state().connected.lock().unwrap().remove(&key);
            result
        }
        Err(e) => {
            state().connected.lock().unwrap().remove(&key);
            Err(e)
        }
    };
    // Registre : date d'expiration, copie de l'IPA pour renouveler.
    let result = result.map(|signed| registry::record(&id, &name, &udid, device_name, &email, &ipa, signed));
    if remove_after {
        let _ = std::fs::remove_file(&ipa);
    }
    result
}

/// Quand Apple dit « maximum de certificats atteint » : on ne révoque que
/// ceux de Sona. `None` (aucun) → l'erreur d'origine remonte.
fn own_certs_only(certs: Vec<isideload::dev::certificates::DevelopmentCertificate>) -> isideload::util::callbacks::MaxCertsCallbackFuture {
    Box::pin(async move {
        let own: Vec<String> = certs
            .iter()
            .filter(|c| c.machine_name.as_deref().is_some_and(|m| m.trim().eq_ignore_ascii_case(LABEL)))
            .filter_map(|c| c.serial_number.clone())
            .collect();
        if !own.is_empty() {
            log_error(&format!("Certificat(s) Sona révoqué(s) pour libérer la place : {}", own.join(", ")));
        }
        Ok(if own.is_empty() { None } else { Some(own) })
    })
}

async fn sign_and_install(
    id: &str,
    mut account: AppleAccount,
    email: String,
    ipa: PathBuf,
    udid: String,
) -> (Result<registry::SignedInfo, String>, Option<AppleAccount>) {
    progress(id, "preparing", -1.0);
    let session = match DeveloperSession::from_account(&mut account).await {
        Ok(s) => s,
        Err(e) => return (Err(short_error(e)), Some(account)),
    };

    let result = async {
        // Par câble, ou en Wi-Fi si l'iPhone est débranché mais sur le même réseau.
        let provider = wifi::provider_for(&udid).await?;
        let mut sideloader = SideloaderBuilder::<isideload::util::callbacks::MaxCertsCallbackBox>::new(session, email)
            .team_selection(TeamSelection::First)
            .max_certs_behavior(MaxCertsBehavior::Prompt(Box::new(own_certs_only)))
            .machine_name(LABEL.to_string())
            .build();

        // `Sideloader::install_app` enchaîne tout mais ne rapporte que la
        // signature : on refait ses étapes pour suivre aussi l'envoi.
        let info = IdeviceInfo::from_device(&provider).await.map_err(short_error)?;
        let team = sideloader.get_team().await.map_err(short_error)?;
        sideloader
            .get_dev_session()
            .ensure_device_registered(&team, &info.name, &info.udid, None)
            .await
            .map_err(short_error)?;
        progress(id, "signing", 0.0);

        let id_for_cb = id.to_string();
        let (signed, _special) = sideloader
            .sign_app(
                ipa,
                Some(team),
                false,
                Some(move |p: f32| {
                    let id = id_for_cb.clone();
                    async move { progress(&id, "signing", (p / 0.5).min(0.95)) }
                }),
            )
            .await
            .map_err(short_error)?;
        progress(id, "signing", 1.0);
        let info = registry::read_signed(&signed);

        progress(id, "installing", 0.0);
        let installed = isideload::sideload::install::install_app(&provider, &signed, |pct: u64| {
            progress(id, "installing", (pct as f32 / 100.0).min(1.0));
        })
        .await
        .map_err(short_error);
        let _ = std::fs::remove_dir_all(&signed);
        installed?;
        progress(id, "done", 1.0);
        Ok(info)
    }
    .await;

    (result, Some(account))
}

/// Télécharge `url` dans `dest` (HTTPS seulement), avec la progression au
/// plus toutes les 100 ms. Renvoie l'empreinte SHA-256.
pub async fn download(url: &str, dest: &std::path::Path, on_progress: impl Fn(u64, u64)) -> Result<String, String> {
    if !url.starts_with("https://") {
        return Err("Adresse de téléchargement refusée : HTTPS obligatoire.".into());
    }
    let client = reqwest::Client::builder()
        .https_only(true)
        .connect_timeout(Duration::from_secs(30))
        .timeout(Duration::from_secs(20 * 60))
        .user_agent(concat!("Sona/", env!("CARGO_PKG_VERSION")))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client.get(url).send().await.map_err(|e| {
        log_error(&format!("téléchargement : {e}"));
        "Téléchargement impossible : vérifie ta connexion Internet, puis réessaie.".to_string()
    })?;
    if !res.status().is_success() {
        return Err(format!("Le téléchargement a échoué (code {}). Réessaie dans un moment.", res.status().as_u16()));
    }
    let total = res.content_length().unwrap_or(0);
    let write_error = |e: std::io::Error| {
        log_error(&format!("écriture : {e}"));
        "Impossible d’enregistrer le fichier : vérifie qu’il reste de la place sur le disque.".to_string()
    };
    let mut file = tokio::fs::File::create(dest).await.map_err(write_error)?;
    let mut hasher = Sha256::new();
    let mut received: u64 = 0;
    let mut last = Instant::now() - Duration::from_secs(1);
    let mut stream = res.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| {
            log_error(&format!("téléchargement : {e}"));
            "Le téléchargement s’est interrompu. Vérifie ta connexion, puis réessaie.".to_string()
        })?;
        hasher.update(&chunk);
        file.write_all(&chunk).await.map_err(write_error)?;
        received += chunk.len() as u64;
        if last.elapsed() >= Duration::from_millis(100) {
            on_progress(received, total);
            last = Instant::now();
        }
    }
    file.flush().await.map_err(write_error)?;
    on_progress(received, total);
    Ok(hex::encode(hasher.finalize()))
}
