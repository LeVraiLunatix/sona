"""Le CLI Supabase ne remplace `env(X)` que si c'est la valeur entière."""
import re
from pathlib import Path


def test_env_references_are_whole_values():
    text = (Path(__file__).parent.parent / "supabase" / "config.toml").read_text(encoding="utf-8")
    values = re.findall(r'^\w+\s*=\s*"([^"]*env\([^"]*)"', text, re.M)
    assert values
    assert [v for v in values if not re.fullmatch(r"env\([A-Z0-9_]+\)", v)] == []


def test_code_emails_have_no_link_that_opens_another_tab():
    """La connexion se finit sur la page déjà ouverte : le code, pas de lien."""
    templates = Path(__file__).parent.parent / "supabase" / "templates"
    for name in ("magic_link", "confirmation", "recovery"):
        text = (templates / f"{name}.html").read_text(encoding="utf-8")
        assert "{{ .Token }}" in text and "<a " not in text, name
    # Changement d'adresse : aucun champ de code dans l'app, le lien reste nécessaire.
    assert "{{ .ConfirmationURL }}" in (templates / "email_change.html").read_text(encoding="utf-8")
