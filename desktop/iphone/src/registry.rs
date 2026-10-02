//! Registre de ce que Sona a installé sur les iPhone (repris de CordLauncher,
//! `iphone_apps.rs`).
//!
//! Chaque installation réussie est notée dans `iphone-apps.json` : l'iPhone,
//! le compte Apple qui a signé, la version et surtout la **date
//! d'expiration** lue dans le profil de provisionnement embarqué (7 jours
//! avec un compte gratuit, un an avec un compte développeur payant). Une
//! copie de l'IPA est gardée dans `ipas\` pour **renouveler** la signature
//! sans rien retélécharger.

use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use idevice::installation_proxy::InstallationProxyClient;
use idevice::IdeviceService;
use serde::{Deserialize, Serialize};

use crate::data_dir;

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct IphoneApp {
    pub id: String,
    pub name: String,
    /// Identifiant réel sur l'iPhone (réécrit à la signature : `com.sona.encre.ABCD1234`).
    pub bundle_id: Option<String>,
    pub version: Option<String>,
    pub udid: String,
    pub device_name: Option<String>,
    pub apple_email: String,
    /// Millisecondes depuis 1970.
    pub installed_at: u64,
    pub expires_at: Option<u64>,
    /// Copie locale de l'IPA, pour renouveler.
    pub ipa: Option<String>,
}

/// Ce qu'on lit dans l'app signée, avant qu'isideload ne la supprime.
#[derive(Default)]
pub struct SignedInfo {
    pub bundle_id: Option<String>,
    pub version: Option<String>,
    pub expires_at: Option<u64>,
}

fn store_path() -> Option<PathBuf> {
    Some(data_dir()?.join("iphone-apps.json"))
}

fn now_ms() -> u64 {
    std::time::SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0)
}

fn load() -> Vec<IphoneApp> {
    store_path()
        .and_then(|p| std::fs::read(p).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn save(list: &[IphoneApp]) -> Result<(), String> {
    let path = store_path().ok_or("Dossier de Sona introuvable.")?;
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::write(path, serde_json::to_vec_pretty(list).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}

/// Les apps suivies, la plus proche de l'expiration d'abord.
pub fn list() -> Vec<IphoneApp> {
    let mut list = load();
    list.sort_by_key(|a| a.expires_at.unwrap_or(u64::MAX));
    list
}

/// Lit l'identifiant, la version et la date d'expiration dans l'app signée.
pub fn read_signed(app_dir: &Path) -> SignedInfo {
    let mut info = SignedInfo::default();
    if let Ok(plist::Value::Dictionary(d)) = plist::Value::from_file(app_dir.join("Info.plist")) {
        info.bundle_id = d.get("CFBundleIdentifier").and_then(|v| v.as_string()).map(str::to_string);
        info.version = d
            .get("CFBundleShortVersionString")
            .or_else(|| d.get("CFBundleVersion"))
            .and_then(|v| v.as_string())
            .map(str::to_string);
    }
    // embedded.mobileprovision = plist XML enveloppé dans une signature CMS :
    // on extrait le XML entre « <?xml » et « </plist> ».
    if let Ok(bytes) = std::fs::read(app_dir.join("embedded.mobileprovision")) {
        info.expires_at = provision_expiry(&bytes);
    }
    info
}

/// Date d'expiration (ms) d'un profil de provisionnement.
pub fn provision_expiry(bytes: &[u8]) -> Option<u64> {
    let start = bytes.windows(5).position(|w| w == b"<?xml")?;
    let end = bytes.windows(8).rposition(|w| w == b"</plist>")?;
    match plist::Value::from_reader_xml(&bytes[start..end + 8]) {
        Ok(plist::Value::Dictionary(d)) => d
            .get("ExpirationDate")
            .and_then(|v| v.as_date())
            .and_then(|date| std::time::SystemTime::from(date).duration_since(UNIX_EPOCH).ok())
            .map(|d| d.as_millis() as u64),
        _ => None,
    }
}

/// Garde une copie de l'IPA (une par app : la dernière installée).
fn cache_ipa(id: &str, source: &Path) -> Option<String> {
    let dir = data_dir()?.join("ipas");
    std::fs::create_dir_all(&dir).ok()?;
    let dest = dir.join(format!("{id}.ipa"));
    if source != dest {
        std::fs::copy(source, &dest).ok()?;
    }
    Some(dest.to_string_lossy().into_owned())
}

/// Note une installation réussie (remplace la précédente pour la même app sur le même iPhone).
pub fn record(id: &str, name: &str, udid: &str, device_name: Option<String>, apple_email: &str, ipa: &Path, signed: SignedInfo) {
    let mut list = load();
    let previous = list.iter().position(|a| a.id == id && a.udid == udid);
    let entry = IphoneApp {
        id: id.to_string(),
        name: name.to_string(),
        bundle_id: signed.bundle_id,
        version: signed.version,
        udid: udid.to_string(),
        device_name: device_name.or_else(|| previous.and_then(|i| list[i].device_name.clone())),
        apple_email: apple_email.to_string(),
        installed_at: now_ms(),
        // Sans profil lisible : 7 jours, la durée d'un compte Apple gratuit.
        expires_at: signed.expires_at.or(Some(now_ms() + 7 * 24 * 3600 * 1000)),
        ipa: cache_ipa(id, ipa),
    };
    match previous {
        Some(i) => list[i] = entry,
        None => list.push(entry),
    }
    let _ = save(&list);
}

/// Oublie une app (elle reste sur l'iPhone ; on arrête juste de la suivre).
pub fn forget(id: &str, udid: &str) -> Result<(), String> {
    let mut list = load();
    list.retain(|a| !(a.id == id && a.udid == udid));
    if !list.iter().any(|a| a.id == id) {
        if let Some(dir) = data_dir() {
            let _ = std::fs::remove_file(dir.join("ipas").join(format!("{id}.ipa")));
        }
    }
    save(&list)
}

/// App présente sur l'iPhone (installation_proxy).
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeviceBundle {
    pub bundle_id: String,
    pub version: Option<String>,
    pub build: Option<String>,
}

/// Apps réellement présentes sur l'iPhone : repère Sona supprimée à la main,
/// ou installée autrement (SideStore, Sideloadly…).
pub async fn device_bundles(udid: String) -> Result<Vec<DeviceBundle>, String> {
    crate::sideload::on_own_thread(move || async move {
        let provider = crate::wifi::provider_for(&udid).await?;
        let mut proxy = InstallationProxyClient::connect(&provider).await.map_err(crate::sideload::short_error)?;
        let apps = proxy.get_apps(Some("User"), None).await.map_err(crate::sideload::short_error)?;
        Ok(apps
            .into_iter()
            .map(|(bundle_id, info)| {
                let get = |key: &str| info.as_dictionary().and_then(|d| d.get(key)).and_then(|v| v.as_string()).map(str::to_string);
                DeviceBundle { version: get("CFBundleShortVersionString"), build: get("CFBundleVersion"), bundle_id }
            })
            .collect())
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expiry_is_read_from_the_provisioning_profile() {
        let mut bytes = b"\x30\x82garbage-cms-header".to_vec();
        bytes.extend_from_slice(br#"<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>ExpirationDate</key><date>2026-10-09T12:00:00Z</date></dict></plist>"#);
        bytes.extend_from_slice(b"\x00\x01signature");
        assert_eq!(provision_expiry(&bytes), Some(1_791_547_200_000));
        assert_eq!(provision_expiry(b"pas un profil"), None);
    }
}
