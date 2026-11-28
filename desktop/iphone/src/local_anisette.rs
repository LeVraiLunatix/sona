//! Anisette locale : l'identité « ce PC » demandée à Apple vient des composants iCloud installés, comme dans
//! Sideloadly. Les serveurs d'anisette publics sont refusés par Apple (401 au provisionnement) depuis novembre 2026.
//!
//! isideload ne sait parler qu'à un serveur d'anisette : on lui en sert un sur 127.0.0.1, avec une identité déjà
//! « provisionnée » pour qu'il ne redemande rien à Apple.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;

use isideload::anisette::remote_v3::RemoteV3AnisetteProvider;
use isideload::util::storage::{InMemoryStorage, SideloadingStorage};
use sha2::{Digest, Sha256};

/// (code à usage unique, identité de la machine).
type Otp = (String, String);

fn otp() -> Result<Otp, String> {
    let common = std::env::var("ProgramFiles(x86)").map_err(|_| "Windows 64 bits requis")?;
    if !std::path::Path::new(&common).join(r"Common Files\Apple\Internet Services\AOSKit.dll").is_file() {
        return Err("iCloud pour Windows absent".into());
    }
    let dir = crate::data_dir().ok_or("dossier de données introuvable")?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let script = dir.join("anisette.ps1");
    std::fs::write(&script, include_str!("anisette.ps1")).map_err(|e| e.to_string())?;
    let root = std::env::var("SystemRoot").map_err(|e| e.to_string())?;
    let mut command = std::process::Command::new(format!(r"{root}\SysWOW64\WindowsPowerShell\v1.0\powershell.exe"));
    command.args(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]).arg(&script);
    #[cfg(windows)]
    std::os::windows::process::CommandExt::creation_flags(&mut command, 0x0800_0000); // pas de fenêtre
    let output = command.stdin(std::process::Stdio::null()).output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).lines().take(3).collect::<Vec<_>>().join(" "));
    }
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).map_err(|e| e.to_string())?;
    match (value["md"].as_str(), value["md_m"].as_str()) {
        (Some(md), Some(md_m)) => Ok((md.into(), md_m.into())),
        _ => Err("réponse d'Apple incomplète".into()),
    }
}

/// Répond à `/v3/get_headers` avec des codes frais ; rend le port d'écoute.
fn serve(source: fn() -> Result<Otp, String>) -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    std::thread::spawn(move || {
        for mut stream in listener.incoming().flatten() {
            let mut reader = BufReader::new(&stream);
            let (mut line, mut length) = (String::new(), 0u64);
            while reader.read_line(&mut line).is_ok_and(|n| n > 0) && line != "\r\n" {
                if let Some(value) = line.to_ascii_lowercase().strip_prefix("content-length:") {
                    length = value.trim().parse().unwrap_or(0);
                }
                line.clear();
            }
            let _ = std::io::copy(&mut reader.take(length.min(65536)), &mut std::io::sink());
            let body = match source() {
                Ok((md, md_m)) => serde_json::json!({ "result": "Headers", "X-Apple-I-MD": md, "X-Apple-I-MD-M": md_m, "X-Apple-I-MD-RINFO": "17106176" }),
                Err(message) => serde_json::json!({ "result": "GetHeadersError", "message": message }),
            }
            .to_string();
            let _ = write!(stream, "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}", body.len());
        }
    });
    Ok(port)
}

/// Branche le fournisseur d'isideload sur ce PC. Erreur si iCloud n'est pas installé ou ne répond pas.
pub fn wire(provider: RemoteV3AnisetteProvider) -> Result<RemoteV3AnisetteProvider, String> {
    let (_, machine) = otp()?;
    // Identifiant d'appareil stable pour ce PC, dérivé de son identité Apple.
    let mut state = plist::Dictionary::new();
    state.insert("keychain_identifier".into(), plist::Value::Data(Sha256::digest(machine.as_bytes())[..16].to_vec()));
    state.insert("adi_pb".into(), plist::Value::Data(vec![0])); // jamais lu : seul notre serveur le reçoit
    let mut bytes = Vec::new();
    plist::to_writer_xml(&mut bytes, &state).map_err(|e| e.to_string())?;
    let storage = InMemoryStorage::new();
    storage.store_data("anisette_state", &bytes).map_err(|e| e.to_string())?;
    Ok(provider.set_url(&format!("http://127.0.0.1:{}", serve(otp)?)).set_storage(Box::new(storage)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_server_speaks_the_v3_protocol() {
        let port = serve(|| Ok(("code".into(), "machine".into()))).unwrap();
        let mut stream = std::net::TcpStream::connect(("127.0.0.1", port)).unwrap();
        stream.write_all(b"POST /v3/get_headers HTTP/1.1\r\ncontent-length: 2\r\n\r\n{}").unwrap();
        let mut answer = String::new();
        stream.read_to_string(&mut answer).unwrap();
        let body: serde_json::Value = serde_json::from_str(answer.split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(body["result"], "Headers");
        assert_eq!(body["X-Apple-I-MD-M"], "machine");
    }

    /// Sur un PC avec iCloud seulement : `cargo test -- --ignored`.
    #[test]
    #[ignore]
    fn this_pc_gives_a_code() {
        let (md, machine) = otp().unwrap();
        assert!(!md.is_empty() && !machine.is_empty());
    }
}
