"""Outils communs pour lire les données JSON embarquées dans une page web
publique (Spotify, Apple Music) quand aucune API ouverte ne donne la même
chose."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator

# En-têtes d'un vrai navigateur : sans eux, certaines pages publiques
# renvoient une coquille vide ou une redirection. ASCII uniquement (httpx
# refuse le reste dans un en-tête).
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def script_json(page: str, *, script_id: str | None = None, script_type: str | None = None) -> list:
    """Contenus JSON des balises <script> portant cet `id` ou ce `type`."""
    found = []
    for match in re.finditer(r"<script\b([^>]*)>(.*?)</script>", page, re.S | re.I):
        attrs, body = match.group(1), match.group(2)
        if script_id and not re.search(rf'\bid=["\']{re.escape(script_id)}["\']', attrs):
            continue
        if script_type and not re.search(rf'\btype=["\']{re.escape(script_type)}["\']', attrs):
            continue
        try:
            found.append(json.loads(body))
        except ValueError:
            continue
    return found


def walk(node) -> Iterator[dict]:
    """Tous les dictionnaires d'un document JSON, dans l'ordre du document
    (parcours en profondeur, parent avant enfants)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def meta_content(page: str, key: str) -> str | None:
    """Valeur d'une balise <meta property|name="key" content="...">."""
    head = page.split("</head>", 1)[0]
    for match in re.finditer(r"<meta\b[^>]*>", head, re.I):
        tag = match.group(0)
        if re.search(rf'\b(?:property|name)=["\']{re.escape(key)}["\']', tag):
            content = re.search(r'\bcontent=["\']([^"\']*)["\']', tag)
            if content:
                return html.unescape(content.group(1)).strip() or None
    return None
