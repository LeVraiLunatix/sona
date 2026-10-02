//! iPhone en Wi-Fi, sans passer par le service Apple Mobile Device (repris de
//! CordLauncher, `wifi.rs`).
//!
//! Le service d'Apple sous Windows voit mal les iPhone en réseau (il les
//! ignore, ou les liste puis échoue à relayer la connexion). Sona fait donc
//! comme iTunes, mais lui-même :
//! 1. quand l'iPhone est branché, il retient son identifiant et son adresse
//!    Wi-Fi (`iphone-devices.json`) ;
//! 2. débranché, il essaie sa dernière adresse IP, puis le cherche sur le
//!    réseau local via Bonjour (`_apple-mobdev2._tcp`) ;
//! 3. il s'y connecte directement (port lockdown 62078) avec le jumelage que
//!    Windows garde pour cet iPhone : la session chiffrée ne s'ouvre qu'avec
//!    le bon iPhone.

use std::collections::HashMap;
use std::future::Future;
use std::net::{IpAddr, Ipv4Addr};
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use idevice::lockdown::LockdownClient;
use idevice::pairing_file::PairingFile;
use idevice::provider::{IdeviceProvider, TcpProvider, UsbmuxdProvider};
use idevice::usbmuxd::{Connection, UsbmuxdAddr, UsbmuxdConnection};
use idevice::{Idevice, IdeviceError, IdeviceService};
use serde::{Deserialize, Serialize};

use crate::LABEL;

// ── iPhone déjà vus par câble ────────────────────────────────────────────────

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct KnownDevice {
    pub udid: String,
    pub name: Option<String>,
    /// Adresse MAC Wi-Fi (minuscules), celle qu'annonce l'iPhone sur le réseau.
    pub wifi_mac: String,
    /// Dernière adresse IP connue : essayée en premier (un iPhone en veille
    /// répond mal aux recherches Bonjour, mais reste joignable).
    #[serde(default)]
    pub last_ip: Option<Ipv4Addr>,
}

fn store_path() -> Option<PathBuf> {
    Some(crate::data_dir()?.join("iphone-devices.json"))
}

pub fn known() -> Vec<KnownDevice> {
    store_path()
        .and_then(|p| std::fs::read(p).ok())
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn save(list: &[KnownDevice]) {
    if let Some(path) = store_path() {
        let _ = std::fs::create_dir_all(path.parent().unwrap());
        let _ = std::fs::write(path, serde_json::to_vec_pretty(list).unwrap_or_default());
    }
}

fn set_last_ip(udid: &str, ip: Ipv4Addr) {
    let mut list = known();
    if let Some(k) = list.iter_mut().find(|k| k.udid == udid) {
        if k.last_ip != Some(ip) {
            k.last_ip = Some(ip);
            save(&list);
        }
    }
}

/// Retient un iPhone branché (identifiant, nom, adresse Wi-Fi). Tant qu'on
/// ne connaît pas son adresse IP, on la cherche en tâche de fond : branché,
/// l'iPhone est éveillé et répond vite.
pub fn remember(udid: &str, name: Option<&str>, wifi_mac: &str) {
    let wifi_mac = wifi_mac.trim().to_lowercase();
    if wifi_mac.is_empty() {
        return;
    }
    let mut list = known();
    let previous = list.iter().position(|k| k.udid == udid);
    let last_ip = previous.and_then(|i| list[i].last_ip);
    let entry = KnownDevice { udid: udid.to_string(), name: name.map(str::to_string), wifi_mac: wifi_mac.clone(), last_ip };
    match previous {
        Some(i) if list[i].wifi_mac == entry.wifi_mac && list[i].name == entry.name => {}
        Some(i) => {
            list[i] = entry;
            save(&list);
        }
        None => {
            list.push(entry);
            save(&list);
        }
    }
    if last_ip.is_none() {
        let udid = udid.to_string();
        std::thread::spawn(move || {
            if let Some(ip) = discover(std::slice::from_ref(&wifi_mac)).get(&wifi_mac) {
                set_last_ip(&udid, *ip);
            }
        });
    }
}

// ── Recherche sur le réseau (Bonjour) ────────────────────────────────────────

/// Dernière recherche : adresse MAC Wi-Fi → IPv4 (gardée 30 s).
static SEEN: Mutex<Option<(Instant, HashMap<String, Ipv4Addr>)>> = Mutex::new(None);

/// Cherche les iPhone annoncés sur le réseau local. S'arrête dès que tous
/// ceux de `wanted` (adresses MAC) sont trouvés, sinon après 8 secondes
/// (la première réponse Bonjour peut mettre plusieurs secondes).
pub fn discover(wanted: &[String]) -> HashMap<String, Ipv4Addr> {
    if let Ok(guard) = SEEN.lock() {
        if let Some((at, seen)) = guard.as_ref() {
            if at.elapsed() < Duration::from_secs(30) && wanted.iter().all(|m| seen.contains_key(m)) {
                return seen.clone();
            }
        }
    }
    let mut found = HashMap::new();
    if let Ok(daemon) = mdns_sd::ServiceDaemon::new() {
        if let Ok(events) = daemon.browse("_apple-mobdev2._tcp.local.") {
            let deadline = Instant::now() + Duration::from_secs(8);
            while let Some(left) = deadline.checked_duration_since(Instant::now()) {
                match events.recv_timeout(left) {
                    Ok(mdns_sd::ServiceEvent::ServiceResolved(info)) => {
                        // Nom de l'instance : « aa:bb:cc:dd:ee:ff@fe80::…-supportsRP-26 ».
                        let mac = info.get_fullname().split('@').next().unwrap_or_default().to_lowercase();
                        if let Some(ip) = info.get_addresses_v4().into_iter().next() {
                            found.insert(mac, ip);
                        }
                        if !wanted.is_empty() && wanted.iter().all(|m| found.contains_key(m)) {
                            break;
                        }
                    }
                    Ok(_) => {}
                    Err(_) => break,
                }
            }
        }
        let _ = daemon.shutdown();
    }
    if let Ok(mut guard) = SEEN.lock() {
        *guard = Some((Instant::now(), found.clone()));
    }
    found
}

// ── Connexion : câble d'abord, sinon Wi-Fi direct ────────────────────────────

/// Fournisseur de connexion vers l'iPhone, par câble (usbmuxd) ou en Wi-Fi.
#[derive(Debug)]
pub enum AnyProvider {
    Usb(UsbmuxdProvider),
    Wifi(TcpProvider),
}

impl IdeviceProvider for AnyProvider {
    fn connect(&self, port: u16) -> Pin<Box<dyn Future<Output = Result<Idevice, IdeviceError>> + Send>> {
        match self {
            Self::Usb(p) => p.connect(port),
            Self::Wifi(p) => p.connect(port),
        }
    }
    fn label(&self) -> &str {
        match self {
            Self::Usb(p) => p.label(),
            Self::Wifi(p) => p.label(),
        }
    }
    fn get_pairing_file(&self) -> Pin<Box<dyn Future<Output = Result<PairingFile, IdeviceError>> + Send>> {
        match self {
            Self::Usb(p) => p.get_pairing_file(),
            Self::Wifi(p) => p.get_pairing_file(),
        }
    }
}

/// Connexion Wi-Fi vérifiée : la session chiffrée ne s'ouvre qu'avec le bon
/// iPhone (son jumelage), jamais avec un autre appareil qui aurait repris l'IP.
async fn verified(ip: Ipv4Addr, pairing_file: PairingFile) -> Option<TcpProvider> {
    let provider = TcpProvider { addr: IpAddr::V4(ip), scope_id: None, pairing_file, label: LABEL.to_string() };
    tokio::time::timeout(Duration::from_secs(5), async {
        let mut lockdown = LockdownClient::connect(&provider).await.ok()?;
        lockdown.start_session(&provider.pairing_file).await.ok()
    })
    .await
    .ok()
    .flatten()?;
    Some(provider)
}

/// Fournisseur Wi-Fi pour un iPhone déjà vu par câble, s'il est sur le réseau :
/// dernière adresse connue d'abord, sinon recherche Bonjour.
pub async fn wifi_provider(mux: &mut UsbmuxdConnection, device: &KnownDevice) -> Option<TcpProvider> {
    let pairing_file = mux.get_pair_record(&device.udid).await.ok()?;
    if let Some(ip) = device.last_ip {
        if let Some(provider) = verified(ip, pairing_file.clone()).await {
            return Some(provider);
        }
    }
    let wanted = vec![device.wifi_mac.clone()];
    let found = tokio::task::spawn_blocking(move || discover(&wanted)).await.ok()?;
    let ip = *found.get(&device.wifi_mac)?;
    if Some(ip) == device.last_ip {
        return None;
    }
    let provider = verified(ip, pairing_file).await?;
    set_last_ip(&device.udid, ip);
    Some(provider)
}

/// Connexion à un iPhone : par câble s'il est branché, sinon en Wi-Fi.
pub async fn provider_for(udid: &str) -> Result<AnyProvider, String> {
    let mut mux = UsbmuxdConnection::default().await.map_err(|_| {
        "Service Apple Mobile Device introuvable : installe iTunes ou « Appareils Apple » depuis le Microsoft Store.".to_string()
    })?;
    if let Ok(devices) = mux.get_devices().await {
        if let Some(d) = devices.iter().find(|d| d.udid == udid && matches!(d.connection_type, Connection::Usb)) {
            return Ok(AnyProvider::Usb(d.to_provider(UsbmuxdAddr::default(), LABEL)));
        }
    }
    let device = known()
        .into_iter()
        .find(|k| k.udid == udid)
        .ok_or_else(|| "L’iPhone n’est pas branché.".to_string())?;
    wifi_provider(&mut mux, &device).await.map(AnyProvider::Wifi).ok_or_else(|| {
        "L’iPhone n’est ni branché ni visible en Wi-Fi : vérifie qu’il est déverrouillé et sur le même réseau que ce PC.".to_string()
    })
}
