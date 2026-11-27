//! Anti « open redirect » : une adresse de retour (Last.fm, lien profond d'une
//! app) n'est acceptée que si elle correspond EXACTEMENT à une entrée de la
//! liste autorisée (schéma + hôte + port), et qu'elle ne cache rien :
//! pas d'identifiants dans l'URL, pas de `\`, pas de `//` en début de chemin.

use url::Url;

/// `allowed` : origines (`https://trysona.fr`, `http://localhost:8000`) ou
/// liens profonds complets (`sona://auth/callback`).
pub fn is_allowed_return_url(candidate: &str, allowed: &[String]) -> bool {
    if candidate.len() > 2048 || candidate.contains('\\') || candidate.chars().any(|c| c.is_control() || c == ' ') {
        return false;
    }
    let Ok(url) = Url::parse(candidate) else { return false };
    if !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    if url.path().starts_with("//") {
        return false;
    }
    allowed.iter().any(|entry| {
        let Ok(rule) = Url::parse(entry) else { return false };
        if rule.scheme() != url.scheme() {
            return false;
        }
        match url.scheme() {
            "https" | "http" => {
                // http seulement pour le développement local.
                if url.scheme() == "http" && !matches!(url.host_str(), Some("localhost") | Some("127.0.0.1")) {
                    return false;
                }
                rule.host_str() == url.host_str() && rule.port_or_known_default() == url.port_or_known_default()
            }
            // Lien profond : même schéma, même « hôte » et même chemin.
            _ => rule.host_str() == url.host_str() && rule.path().trim_end_matches('/') == url.path().trim_end_matches('/'),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn allow() -> Vec<String> {
        vec!["https://trysona.fr".into(), "http://localhost:8000".into(), "sona://auth/callback".into()]
    }

    #[test]
    fn accepts_exact_origins_and_deep_link() {
        let a = allow();
        assert!(is_allowed_return_url("https://trysona.fr/", &a));
        assert!(is_allowed_return_url("https://trysona.fr/web/?x=1#/settings", &a));
        assert!(is_allowed_return_url("http://localhost:8000/web/", &a));
        assert!(is_allowed_return_url("sona://auth/callback", &a));
        assert!(is_allowed_return_url("sona://auth/callback?code=abc", &a));
    }

    #[test]
    fn rejects_lookalikes_and_tricks() {
        let a = allow();
        for bad in [
            "https://trysona.fr.evil.com/",
            "https://evil.com/?u=https://trysona.fr",
            "https://trysona.fr@evil.com/",
            "https://user:pw@trysona.fr/",
            "https://trysona.fr:444/",
            "http://trysona.fr/",
            "http://localhost:9999/",
            "https://trysona.fr\\@evil.com",
            "https://trysona.fr//evil.com",
            "//evil.com",
            "javascript:alert(1)",
            "data:text/html,x",
            "sona://evil/callback",
            "sona://auth/other",
            "https://sub.trysona.fr/",
            "",
            "https://trysona.fr/ x",
        ] {
            assert!(!is_allowed_return_url(bad, &a), "doit refuser {bad:?}");
        }
    }

    #[test]
    fn empty_allow_list_refuses_everything() {
        assert!(!is_allowed_return_url("https://trysona.fr/", &[]));
    }
}
