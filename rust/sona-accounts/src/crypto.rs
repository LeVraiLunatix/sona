//! Chiffrement AES-256-GCM des secrets des services connectés (clé de session
//! Last.fm). Format : `v1.<nonce en base64url>.<texte chiffré en base64url>`.
//! La clé (SECRETS_ENCRYPTION_KEY, 32 octets en base64) n'existe que sur le serveur.

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use base64::Engine;
use rand::RngCore;

#[derive(Debug, thiserror::Error)]
pub enum CryptoError {
    #[error("clé de chiffrement absente ou invalide (32 octets en base64 attendus)")]
    BadKey,
    #[error("secret illisible")]
    BadCiphertext,
}

pub struct Vault {
    cipher: Aes256Gcm,
}

impl Vault {
    pub fn from_base64(key: &str) -> Result<Self, CryptoError> {
        let bytes = STANDARD.decode(key.trim()).map_err(|_| CryptoError::BadKey)?;
        if bytes.len() != 32 {
            return Err(CryptoError::BadKey);
        }
        Ok(Vault { cipher: Aes256Gcm::new_from_slice(&bytes).map_err(|_| CryptoError::BadKey)? })
    }

    /// `context` (ex. identifiant du compte) est authentifié mais pas stocké : un
    /// secret copié sur la ligne d'un autre compte ne se déchiffre pas.
    pub fn seal(&self, plaintext: &str, context: &str) -> String {
        let mut nonce = [0u8; 12];
        rand::thread_rng().fill_bytes(&mut nonce);
        let ct = self
            .cipher
            .encrypt(Nonce::from_slice(&nonce), aes_gcm::aead::Payload { msg: plaintext.as_bytes(), aad: context.as_bytes() })
            .expect("AES-GCM : chiffrement en mémoire");
        format!("v1.{}.{}", URL_SAFE_NO_PAD.encode(nonce), URL_SAFE_NO_PAD.encode(ct))
    }

    pub fn open(&self, sealed: &str, context: &str) -> Result<String, CryptoError> {
        let mut parts = sealed.split('.');
        let (Some("v1"), Some(n), Some(c), None) = (parts.next(), parts.next(), parts.next(), parts.next()) else {
            return Err(CryptoError::BadCiphertext);
        };
        let nonce = URL_SAFE_NO_PAD.decode(n).map_err(|_| CryptoError::BadCiphertext)?;
        let ct = URL_SAFE_NO_PAD.decode(c).map_err(|_| CryptoError::BadCiphertext)?;
        if nonce.len() != 12 {
            return Err(CryptoError::BadCiphertext);
        }
        let pt = self
            .cipher
            .decrypt(Nonce::from_slice(&nonce), aes_gcm::aead::Payload { msg: &ct, aad: context.as_bytes() })
            .map_err(|_| CryptoError::BadCiphertext)?;
        String::from_utf8(pt).map_err(|_| CryptoError::BadCiphertext)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const KEY: &str = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=";

    #[test]
    fn roundtrip_and_randomised() {
        let v = Vault::from_base64(KEY).unwrap();
        let a = v.seal("session-key-123", "user-1");
        let b = v.seal("session-key-123", "user-1");
        assert_ne!(a, b, "nonce différent à chaque chiffrement");
        assert!(!a.contains("session-key"));
        assert_eq!(v.open(&a, "user-1").unwrap(), "session-key-123");
    }

    #[test]
    fn secret_is_bound_to_its_account() {
        let v = Vault::from_base64(KEY).unwrap();
        let a = v.seal("k", "user-1");
        assert!(v.open(&a, "user-2").is_err());
    }

    #[test]
    fn tampering_and_garbage_are_rejected() {
        let v = Vault::from_base64(KEY).unwrap();
        let a = v.seal("k", "u");
        let mut broken = a.clone();
        broken.push('A');
        assert!(v.open(&broken, "u").is_err());
        assert!(v.open("n'importe quoi", "u").is_err());
        assert!(v.open("v2.a.b", "u").is_err());
    }

    #[test]
    fn bad_keys() {
        assert!(Vault::from_base64("pas du base64 !").is_err());
        assert!(Vault::from_base64("c2hvcnQ=").is_err());
    }
}
