//! Signature des appels Last.fm : MD5 des paramètres triés par nom, noms et
//! valeurs collés, suivis du secret. `format` et `callback` n'entrent pas
//! dans la signature.

use md5::{Digest, Md5};
use std::collections::BTreeMap;

pub fn sign(params: &BTreeMap<&str, String>, secret: &str) -> String {
    let mut raw = String::new();
    for (k, v) in params {
        if *k == "format" || *k == "callback" {
            continue;
        }
        raw.push_str(k);
        raw.push_str(v);
    }
    raw.push_str(secret);
    hex::encode(Md5::digest(raw.as_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn md5_known_vector() {
        // MD5("") = d41d8cd98f00b204e9800998ecf8427e
        assert_eq!(hex::encode(Md5::digest(b"")), "d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(hex::encode(Md5::digest(b"abc")), "900150983cd24fb0d6963f7d28e17f72");
    }

    #[test]
    fn signature_sorts_and_ignores_format() {
        let mut p = BTreeMap::new();
        p.insert("method", "auth.getSession".to_string());
        p.insert("api_key", "KEY".to_string());
        p.insert("token", "TOK".to_string());
        p.insert("format", "json".to_string());
        // api_keyKEYmethodauth.getSessiontokenTOKSECRET
        let expected = hex::encode(Md5::digest(b"api_keyKEYmethodauth.getSessiontokenTOKSECRET"));
        assert_eq!(sign(&p, "SECRET"), expected);
    }

    #[test]
    fn insertion_order_does_not_matter() {
        let mut a = BTreeMap::new();
        a.insert("b", "2".to_string());
        a.insert("a", "1".to_string());
        let mut b = BTreeMap::new();
        b.insert("a", "1".to_string());
        b.insert("b", "2".to_string());
        assert_eq!(sign(&a, "s"), sign(&b, "s"));
    }
}
