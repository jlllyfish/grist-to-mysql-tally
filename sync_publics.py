import os

import requests
from dotenv import load_dotenv

load_dotenv()

GRIST_URL = os.getenv("GRIST_SERVER") + "/api"
DOC_ID = os.getenv("GRIST_DOC_2_ID")
headers = {
    "Authorization": f"Bearer {os.getenv('GRIST_API_KEY')}",
    "Content-Type": "application/json",
}


def get_records(table):
    r = requests.get(
        f"{GRIST_URL}/docs/{DOC_ID}/tables/{table}/records", headers=headers
    )
    r.raise_for_status()
    return r.json()["records"]


def add_records(table, records):
    r = requests.post(
        f"{GRIST_URL}/docs/{DOC_ID}/tables/{table}/records",
        json={"records": records},
        headers=headers,
    )
    r.raise_for_status()
    print(f"{len(records)} lignes ajoutées dans {table}")


def delete_records(table, ids):
    r = requests.post(
        f"{GRIST_URL}/docs/{DOC_ID}/tables/{table}/data/delete",
        json=ids,
        headers=headers,
    )
    r.raise_for_status()
    print(f"{len(ids)} lignes supprimées dans {table}")


# 1. Lire Tableau_recap_stage
rows = get_records("Tableau_recap_stage")

# 2. Calculer l'état cible (id_stage, public)
cible = []
for row in rows:
    id_stage = row["id"]
    valeurs = row["fields"].get("Public", "") or ""
    for val in valeurs.split(","):
        val = val.strip()
        if val:
            cible.append((id_stage, val))

cible_set = set(cible)

# 3. Lire l'état actuel de Publics
existants = get_records("Publics")
existant_index = {}  # (id_stage, public) -> grist_id
for rec in existants:
    key = (rec["fields"].get("id_stage"), rec["fields"].get("public"))
    existant_index[key] = rec["id"]

existant_set = set(existant_index.keys())

# 4. Calculer les différences
a_ajouter = cible_set - existant_set
a_supprimer = existant_set - cible_set

print(
    f"À ajouter : {len(a_ajouter)}, à supprimer : {len(a_supprimer)}, inchangés : {len(cible_set & existant_set)}"
)

# 5. Supprimer les obsolètes
if a_supprimer:
    ids_a_supprimer = [existant_index[key] for key in a_supprimer]
    delete_records("Publics", ids_a_supprimer)

# 6. Ajouter les nouveaux
if a_ajouter:
    records = [
        {"fields": {"id_stage": id_stage, "public": pub}} for id_stage, pub in a_ajouter
    ]
    add_records("Publics", records)
