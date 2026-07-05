# 🏠 Surveillance des disponibilités Fac-Habitat / Smerra

Vérifie **toutes les heures, 24h/24, gratuitement** les pages de tes résidences et t'alerte
(email + Telegram) dès qu'une disponibilité apparaît. Tourne sur GitHub Actions : ton PC peut être éteint.

Le script surveille 2 choses par résidence :
- le badge global de la page (« Complet » / « Dispo à venir » / « Dispo immédiate »)
- le **statut de chaque type de logement** (T1, T1 BIS...) dans le module de réservation w2.fac-habitat.com — la vraie source des dispos

Statuts reconnus (vocabulaire réel du site) et hiérarchie :

| Rang | Statut logement | Badge résidence |
|------|-----------------|-----------------|
| 0 fermé | Complet, Indisponible | Complet |
| 1 bientôt | A venir | Dispo à venir |
| 2 ouvert | Disponible | Dispo immédiate |

**Toute montée de rang déclenche une alerte** : Complet → A venir (⏳ prépare ton dossier) comme A venir → Disponible (✅ postule). Une redescente (Disponible → Complet) est silencieuse. Un statut au vocabulaire inconnu est traité comme « Disponible » par prudence : mieux vaut une fausse alerte qu'une occasion ratée.

## Installation (10 minutes)

### 1. Créer le dépôt GitHub
1. Crée un compte sur https://github.com si besoin.
2. Clique **+** (en haut à droite) → **New repository** → nom : `fac-habitat-monitor` → coche **Private** → **Create repository**.
3. Sur la page du dépôt : **uploading an existing file** (ou Add file → Upload files), puis **glisse-dépose le dossier entier** `fac-habitat-monitor` (les 4 fichiers + le dossier `.github`). Clique **Commit changes**.
   - Si le dossier `.github` n'est pas passé : Add file → **Create new file**, nomme-le `.github/workflows/monitor.yml` et colle le contenu du fichier.

### 2. Activer et tester
1. Onglet **Actions** → si demandé, clique **I understand... enable them**.
2. Clique sur **Surveillance logements Fac-Habitat** → bouton **Run workflow** → **Run workflow**.
3. Attends ~1 min : le run doit être vert ✅. Le premier passage enregistre l'état de référence (pas d'alerte).

### 3. Alertes par email
Quand une dispo apparaît, le robot crée une **issue** assignée à toi → GitHub t'envoie un **email automatiquement** (à l'adresse de ton compte GitHub).
Vérifie que c'est activé : https://github.com/settings/notifications → section *Participating, @mentions and custom* → **Email** coché.

### 4. Alertes Telegram (optionnel mais recommandé : notification push instantanée)
1. Dans Telegram, parle à **@BotFather** → `/newbot` → suis les étapes → copie le **token** (ex : `123456:ABC-DEF...`).
2. Parle à **@userinfobot** → il te donne ton **chat id** (un nombre).
3. **Envoie n'importe quel message à ton nouveau bot** (obligatoire pour qu'il puisse t'écrire).
4. Dans ton dépôt : **Settings → Secrets and variables → Actions → New repository secret** :
   - `TELEGRAM_BOT_TOKEN` = le token
   - `TELEGRAM_CHAT_ID` = le chat id

## Utilisation

- **Ajouter/retirer une résidence** : édite `residences.json` directement sur GitHub (icône crayon), ajoute un bloc `{"nom": "...", "url": "https://logement.smerra.fr/residence-etudiante/..."}` et committe.
- **Changer la fréquence** : dans `.github/workflows/monitor.yml`, remplace `"0 * * * *"` par `"*/30 * * * *"` (30 min) ou `"*/15 * * * *"` (15 min). Évite en dessous de 15 min (inutile et risque de blocage par le site).
- **Voir l'état actuel** : fichier `state.json` du dépôt (mis à jour à chaque passage).
- **Historique** : chaque changement (y compris les retours à Complet, non alertés) est ajouté à `historique.csv` — visible en tableau directement sur GitHub, ou dans Excel. Utile pour repérer les résidences qui bougent le plus, les périodes favorables et la durée des fenêtres de dispo.

## Bon à savoir

- Dépôt privé gratuit : 2000 min/mois de GitHub Actions ; un passage ≈ 1 min → même toutes les 30 min tu restes largement dans le gratuit.
- Les crons GitHub peuvent avoir quelques minutes de retard aux heures pleines : normal.
- Le script n'alerte que sur les **nouvelles** dispos (pas de spam) et ne génère pas de fausse alerte si le site est momentanément injoignable.
- ⚠️ L'alerte te dit où postuler, mais la candidature reste à faire par toi, vite : lien direct `#reservation` inclus dans chaque alerte.
