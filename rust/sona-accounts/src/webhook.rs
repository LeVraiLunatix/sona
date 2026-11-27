//! Signature « Standard Webhooks » des hooks d'authentification Supabase
//! (en-têtes `webhook-id`, `webhook-timestamp`, `webhook-signature: v1,<base64>`).

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// Secret au format `v1,whsec_<base64>` (ou `whsec_<base64>`).
fn key_bytes(secret: &str) -> Option<Vec<u8>> {
    let s = secret.strip_prefix("v1,").unwrap_or(secret);
    let s = s.strip_prefix("whsec_").unwrap_or(s);
    STANDARD.decode(s).ok()
}

pub fn sign(secret: &str, id: &str, timestamp: i64, body: &[u8]) -> Option<String> {
    let mut mac = HmacSha256::new_from_slice(&key_bytes(secret)?).ok()?;
    mac.update(format!("{id}.{timestamp}.").as_bytes());
    mac.update(body);
    Some(format!("v1,{}", STANDARD.encode(mac.finalize().into_bytes())))
}

/// Vrai si l'une des signatures de l'en-tête est valide et l'horodatage récent (5 min).
pub fn verify(secret: &str, id: &str, timestamp: &str, signatures: &str, body: &[u8], now: i64) -> bool {
    let Ok(ts) = timestamp.parse::<i64>() else { return false };
    if (now - ts).abs() > 300 {
        return false;
    }
    let Some(key) = key_bytes(secret) else { return false };
    for candidate in signatures.split(' ') {
        let Some(b64) = candidate.strip_prefix("v1,") else { continue };
        let Ok(expected) = STANDARD.decode(b64) else { continue };
        let Ok(mut mac) = HmacSha256::new_from_slice(&key) else { return false };
        mac.update(format!("{id}.{ts}.").as_bytes());
        mac.update(body);
        if mac.verify_slice(&expected).is_ok() {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    const SECRET: &str = "v1,whsec_dGVzdC1ob29rLXNlY3JldA==";

    #[test]
    fn valid_signature_passes() {
        let sig = sign(SECRET, "msg_1", 1_700_000_000, b"{\"a\":1}").unwrap();
        assert!(verify(SECRET, "msg_1", "1700000000", &sig, b"{\"a\":1}", 1_700_000_010));
        // Plusieurs signatures (rotation de secret) : une bonne suffit.
        assert!(verify(SECRET, "msg_1", "1700000000", &format!("v1,AAAA {sig}"), b"{\"a\":1}", 1_700_000_010));
    }

    #[test]
    fn tampering_replay_and_garbage_fail() {
        let sig = sign(SECRET, "msg_1", 1_700_000_000, b"body").unwrap();
        assert!(!verify(SECRET, "msg_1", "1700000000", &sig, b"body2", 1_700_000_010));
        assert!(!verify(SECRET, "msg_2", "1700000000", &sig, b"body", 1_700_000_010));
        assert!(!verify(SECRET, "msg_1", "1700000000", &sig, b"body", 1_700_001_000), "trop vieux");
        assert!(!verify(SECRET, "msg_1", "pas-un-nombre", &sig, b"body", 0));
        assert!(!verify(SECRET, "msg_1", "1700000000", "", b"body", 1_700_000_010));
        assert!(!verify("v1,whsec_autre", "msg_1", "1700000000", &sig, b"body", 1_700_000_010));
    }
}
