# Grist → MySQL

Synchronisation de tables Grist vers une base MySQL.

- **`main.py`** — migration initiale (à lancer une fois)
- **`sync_publics.py`** — éclatement de la colonne `Public` en lignes atomiques dans la table Grist `Publics`
- **`sync.py`** — synchronisation quotidienne avec upsert + suppression

---

## Prérequis

- Python 3.11+
- Une base MySQL existante
- Une clé API Grist (Profile Settings → API Key)

---

## Installation

```bash
git clone https://github.com/ton-user/ton-repo.git
cd ton-repo
pip install -r requirements.txt
cp .env.example .env
```

Remplir `.env` avec tes credentials.

---

## Configuration

### `.env`

| Variable | Description | Exemple |
|---|---|---|
| `GRIST_API_KEY` | Clé API Grist | `abc123...` |
| `GRIST_SERVER` | URL de l'instance Grist | `https://grist.numerique.gouv.fr` |
| `GRIST_DOC_1_ID` | ID du document Grist principal | `a26eXyLMFwAipED67oFUkJ` |
| `GRIST_DOC_1_TABLES` | Tables à synchroniser (doc 1), séparées par des virgules | `Formulaire_contact_OTP,Tally_old` |
| `GRIST_DOC_2_ID` | ID du document Grist secondaire | `9g87WsK9KWp1xAZAfvSAYu` |
| `GRIST_DOC_2_TABLES` | Tables à synchroniser (doc 2), séparées par des virgules | `Tableau_recap_stage,Publics` |
| `MYSQL_HOST` | Hôte MySQL | `cj1256827-001.eu.clouddb.ovh.net` |
| `MYSQL_PORT` | Port MySQL | `3306` |
| `MYSQL_USER` | Utilisateur MySQL | `jellyfish` |
| `MYSQL_PASSWORD` | Mot de passe MySQL | `...` |
| `MYSQL_DATABASE` | Nom de la base | `pony_express` |
| `DRY_RUN` | `true` = lecture seule, rien écrit | `false` |
| `LOG_LEVEL` | Verbosité des logs | `INFO` |

### `sync.py` — clés métier

Avant de lancer `sync.py`, renseigner la colonne clé unique de chaque table dans le dictionnaire `KEY_COLUMNS` en haut du fichier :

```python
KEY_COLUMNS: dict[str, str] = {
    "Tally_old":             "submission_id",
    "Retours_Tally_new":     "submission_id",
    "Users_instance_dev":    "id_bdd",
    "Formulaire_contact_OTP": "Email",
    "Tableau_recap_stage":   "id_stage",
    "Publics":               "uuid",
}
```

---

## Utilisation

### Migration initiale

```bash
# Vérifier la lecture Grist sans rien écrire
DRY_RUN=true python main.py

# Migrer structure + données
python main.py
```

### Synchronisation

```bash
# 1. Éclater la colonne Public dans Grist
python sync_publics.py

# 2. Synchroniser Grist → MySQL
python sync.py
```

Le rapport affiché indique pour chaque table :
- `+` records insérés
- `~` records mis à jour
- `-` records supprimés
- `=` records inchangés

---

## Table `Publics`

La table `Publics` est une table dérivée de `Tableau_recap_stage`. Elle éclate la colonne `Public` (valeurs séparées par des virgules) en lignes atomiques, une valeur par ligne.

Elle est utilisée dans Metabase pour alimenter un filtre dropdown par type de public, via une sous-requête :

```sql
SELECT * FROM Tableau_recap_stage
WHERE 1=1
[[AND grist_id IN (
    SELECT id_stage FROM Publics WHERE public = {{public_filtre}}
)]]
```

Chaque ligne de `Publics` possède un `uuid` (colonne trigger Grist) servant de clé métier unique pour l'upsert MySQL.

---

## Automatisation (GitHub Actions)

La sync tourne automatiquement chaque jour à 6h UTC via `.github/workflows/sync.yml`.

**Secrets à configurer** dans Settings → Secrets and variables → Actions :

`GRIST_API_KEY`, `GRIST_SERVER`, `GRIST_DOC_1_ID`, `GRIST_DOC_1_TABLES`, `GRIST_DOC_2_ID`, `GRIST_DOC_2_TABLES`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`

Pour déclencher manuellement : onglet **Actions** → **Sync Grist → MySQL** → **Run workflow**.

---

## Structure du projet

| Fichier | Rôle |
|---|---|
| `grist_client.py` | Client HTTP Grist avec retry et chunking |
| `reader.py` | Lecture et filtrage des tables/colonnes Grist |
| `mapper.py` | Conversion types Grist → types MySQL |
| `mysql_writer.py` | Création tables MySQL et import des données |
| `config.py` | Chargement de la configuration depuis `.env` |
| `main.py` | Migration initiale |
| `sync_publics.py` | Éclatement de la colonne Public dans Grist |
| `sync.py` | Synchronisation quotidienne |

---

## Notes

- Les tables techniques Grist (`_grist_*`) sont automatiquement exclues.
- Les noms de colonnes dépassant 64 caractères sont tronqués (limite MySQL).
- Les colonnes de type formule Grist ne sont pas importées (exception : colonnes trigger).
- La colonne `grist_id` est ajoutée à chaque table MySQL pour stocker l'ID Grist original.
- La table `Publics` utilise un `uuid` (colonne trigger) comme clé métier pour garantir l'unicité lors de l'upsert.
