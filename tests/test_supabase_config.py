"""Le CLI Supabase ne remplace `env(X)` que si c'est la valeur entière."""
import re
from pathlib import Path


def test_env_references_are_whole_values():
    text = (Path(__file__).parent.parent / "supabase" / "config.toml").read_text(encoding="utf-8")
    values = re.findall(r'^\w+\s*=\s*"([^"]*env\([^"]*)"', text, re.M)
    assert values
    assert [v for v in values if not re.fullmatch(r"env\([A-Z0-9_]+\)", v)] == []
