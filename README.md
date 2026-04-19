# Grist → MySQL

Synchronisation de tables Grist vers une base MySQL.

- **`main.py`** — migration initiale (à lancer une fois)
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
| `GRIST_DOC_ID` | ID du document Grist (dans l'URL) | `a26eXyLMFwAipED67oFUkJ` |
| `TABLES_TO_SYNC` | Tables à migrer, séparées par des virgules. Laisser vide = toutes | `Tally_old,Retours_Tally_new` |
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
    "Tally_old":        "submission_id",
    "Retours_Tally_new": "submission_id",
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
python sync.py
```

Le rapport affiché indique pour chaque table :
- `+` records insérés
- `~` records mis à jour
- `-` records supprimés
- `=` records inchangés

---

## Automatisation (GitHub Actions)

La sync tourne automatiquement chaque jour à 6h UTC via `.github/workflows/sync.yml`.

**Secrets à configurer** dans Settings → Secrets and variables → Actions :

`GRIST_API_KEY`, `GRIST_DOC_ID`, `GRIST_SERVER`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, `TABLES_TO_SYNC`

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
| `sync.py` | Synchronisation quotidienne |

---

## Notes

- Les tables techniques Grist (`_grist_*`) sont automatiquement exclues.
- Les noms de colonnes dépassant 64 caractères sont tronqués (limite MySQL).
- Les colonnes de type formule Grist ne sont pas importées.
- La colonne `grist_id` est ajoutée à chaque table MySQL pour stocker l'ID Grist original.
