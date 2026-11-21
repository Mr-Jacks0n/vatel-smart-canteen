# Vatel Smart Canteen

> **Réserver, préparer juste, servir vite, payer simplement.**

Application web responsive (mobile-first pour élèves, personnel et parents ; bureau pour équipe cantine et administration) développée dans le cadre du Hackathon Cantine Vatel.

- **Démo en ligne (Render)** : https://vatel-smart-canteen.onrender.com/
- **Dépôt GitHub** : https://github.com/Mr-Jacks0n/vatel-smart-canteen

---

## 1. Problèmes traités

- Files d'attente aux heures de pointe grâce au **ticket QR** et au **code court 6 caractères**.
- Gaspillage alimentaire réduit par la **réservation avant 18h00 la veille**, le choix explicite **« Sans entrée » / « Sans dessert » / « Je ne mange pas ce jour »**, et la **consolidation cuisine**.
- Sécurité alimentaire via le **profil alimentaire** (allergies, intolérances, régimes) et l'**alerte allergène avec confirmation obligatoire côté serveur**.
- Transparence financière complète pour les familles (espace parent dédié) et l'administration.

---

## 2. Fonctionnalités par rôle

- **Élève / Personnel** : menu de la semaine (Entrées / Plats / Desserts), composition du repas complet (prix fixe + portion supplémentaire + option livraison), « Je ne mange pas ce jour », ticket QR plein écran, « Solde Vatel Cantine » (débit programmé à la veille, fréquence journalière ou hebdomadaire, débit automatique activable), ou badge **« Année soldée »** sans affichage de solde, profil alimentaire, notifications. *(Département obligatoire pour le personnel.)*
- **Parent** : vue consolidée des enfants liés, recharge ponctuelle, prépaiement annuel (« Année soldée »), réglages de débit, historique financier unifié et typé, gestion du profil alimentaire, alertes solde faible / insuffisant.
- **Équipe cantine** : consolidation cuisine par plat/catégorie avec allergies du jour, validation comptoir par QR ou code court sans double retrait, gestion des livraisons par lieu.
- **Administration** : tableau de bord opérationnel et financier (Chart.js local), gestion des menus et capacités, commandes filtrables, gestion des comptes/départements/liens parents, confirmation des virements bancaires et activation manuelle de forfaits avec motif, déclenchement de la clôture (`run_closure`), journal d'audit.

---

## 3. Module financier (100 % dématérialisé)

- **Trois encaissements distincts**, jamais confondus dans les historiques ni dans les rapports :
  1. `TOPUP` — **Recharge ponctuelle** (crédite le Solde Vatel Cantine)
  2. `ANNUAL_PREPAYMENT` — **Prépaiement annuel** (active le forfait « Année soldée », ne crédite pas le portefeuille)
  3. `PICKUP` — **Paiement au retrait** (règle un dû avant remise, ne touche pas le portefeuille)
- **Zéro espèce** : Mobile Money simulé (Wave, Orange Money, MTN MoMo, Moov Money), carte bancaire simulée (aucune donnée de carte saisie ni stockée), et virement bancaire réservé au prépaiement annuel (confirmé par un ADMIN).
- **Débit à la veille & clôture idempotente** (`python manage.py run_closure`) : aucun débit au moment de la réservation ; exécution la veille avec repli automatique en « À régler au retrait » (ou annulation) et notifications en cas de solde insuffisant.

---

## 4. Architecture & Stack

- **Backend** : Monolithe Django 5.2 LTS (`config` + 9 applications : `core`, `accounts`, `menus`, `wallet`, `payments`, `reservations`, `parents`, `canteen`, `dashboard`), logique métier isolée dans `services.py`.
- **Base de données** : PostgreSQL en production (`psycopg[binary] 3.x`, `dj-database-url`), contraintes SQL `CHECK` et `UniqueConstraint` partielles, transactions atomiques + `select_for_update`.
- **Frontend** : Templates Django, Bootstrap 5.3, Bootstrap Icons, HTMX 2, Chart.js 4 — **100 % servis localement depuis `static/vendor/`** (0 CDN).
- **QR codes** : `segno` (SVG généré côté serveur).

---

## 5. Sécurité principale

- Hachage **Argon2** en premier (`argon2-cffi`), protection anti-force brute **django-axes 8.3.x** (5 échecs → 15 min).
- Contrôle d'accès par rôle sur chaque vue et filtrage anti-IDOR renvoyant `404`.
- CSRF actif partout (`hx-headers` pour HTMX), toutes les actions mutantes en `POST`.
- En-têtes stricts : `CSP 'self'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`, HSTS + HTTPS forcé quand `DEBUG=False`.
- Administration Django déplacée à `/gestion-securisee/` ; `WalletTransaction` et `Payment` en lecture seule.

---

## 6. Installation locale & démarrage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Éditer .env (notamment SECRET_KEY et DEMO_PASSWORD)
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Exécuter la suite de tests automatisés :

```bash
python manage.py check
python manage.py test
```

---

## 7. Comptes de démonstration (`seed_demo`)

*(Les mots de passe sont lus depuis `DEMO_PASSWORD` et communiqués au jury séparément.)*

| Rôle | Identifiant e-mail | Particularité |
|---|---|---|
| Administrateur | `admin@vatel.demo` | Accès complet tableau de bord, clôture, virements |
| Équipe cantine | `equipe@vatel.demo` | Cuisine, comptoir QR, livraisons |
| Parent (2 enfants) | `fatou.parent@vatel.demo` | Liée à Aya (portefeuille) et Kader (Année soldée) |
| Parent | `jean.parent@vatel.demo` | Lié à Sali (solde faible + virement en attente) |
| Élève | `aya.eleve@vatel.demo` | Solde 10 000 FCFA, allergie arachides |
| Élève (Forfait) | `kader.forfait@vatel.demo` | Badge « Année soldée », aucun solde affiché |
| Élève (Solde faible) | `sali.soldefaible@vatel.demo` | Solde 1 000 FCFA, intolérance lait |
| Élève (Sans solde) | `yao.sanssolde@vatel.demo` | Solde 0 FCFA, débit auto désactivé |
| Personnel | `claire.pedagogie@vatel.demo` | Département Pédagogie, débit hebdomadaire, livraison |
| Personnel | `marc.direction@vatel.demo` | Département Direction, « Je ne mange pas ce jour » |

---

## 8. Limites connues & vision produit

Les paiements Mobile Money, carte et virement sont simulés via une interface prestataire isolée (`payments/providers.py`). La gestion des stocks/recettes, notifications SMS/e-mail/push, intégration réelle des API opérateurs, reçus PDF et prévisions IA relèvent de la vision produit présentée au jury.

---

## 9. Crédits & licences

Django (BSD), Bootstrap 5.3 & Bootstrap Icons (MIT), HTMX (BSD-2-Clause), Chart.js (MIT), segno (BSD-3-Clause), django-axes (MIT), WhiteNoise (MIT).
