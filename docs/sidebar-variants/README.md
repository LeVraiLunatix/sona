# Menu latéral : trois variantes, une retenue

Les trois maquettes (HTML autonome + capture) montrent le même contenu, fermé (rail de 72 px) et ouvert (panneau de 264 px) :

| | Variante | Caractère |
|---|---|---|
| ![A](variante-A-pilule.png) | **A — Pilule** | noir pur collé au bord de la fenêtre, filet très fin, pastille douce pour la page active + point discret |
| ![B](variante-B-flottante.png) | B — Flottante | carte arrondie détachée du bord, léger flou, pastille pleine claire |
| ![C](variante-C-filet.png) | C — Filet | comme A, rayons plus francs, trait d'accent sur le bord gauche |

## Choix : A « Pilule »

Critères du cahier des charges, dans l'ordre :

1. **Fond noir pur, bordure très fine** : A et C le font ; B pose une carte grise sur le fond, ce qui crée une seconde surface et mange de la largeur utile.
2. **Élément actif : pastille douce + petit indicateur discret, « sans bordure agressive »** : B utilise une pastille blanche pleine (très contrastée, trop présente quand elle est sur chaque page) ;
   C ajoute une barre verticale qui ressemble à une bordure ; A garde une pastille translucide et un simple point de 4 px.
3. **Formes douces, rayons généreux** : A et B (16 px) ; C (10 px) est plus sec.
4. **Aucun bug visuel possible** : A est la plus simple à animer proprement : un seul rectangle noir rogné par `clip-path`, un filet qui glisse, des icônes qui ne bougent jamais (même colonne de 48 px dans les deux états).
   B demande de faire grandir une carte avec ses marges et ses ombres (l'ombre serait rognée) ; C ajoute un indicateur qui déborde du rail.
5. **Cohérence avec l'app** : le contenu de Sona est déjà un grand panneau arrondi sur fond sombre ; une carte flottante de plus (B) alourdit l'ensemble.

Implémentation : `web/sidebar.css` et `web/sidebar.js` (voir leurs commentaires), testée dans `tests/ui/accounts.mjs`.
