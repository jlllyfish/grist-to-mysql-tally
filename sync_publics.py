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


def delete_all(table):
    records = get_records(table)
    ids = [r["id"] for r in records]
    if ids:
        r = requests.post(
            f"{GRIST_URL}/docs/{DOC_ID}/tables/{table}/data/delete",
            json=ids,
            headers=headers,
        )
        r.raise_for_status()
        print(f"{len(ids)} lignes supprimées dans {table}")


def insert_records(table, records):
    r = requests.post(
        f"{GRIST_URL}/docs/{DOC_ID}/tables/{table}/records",
        json={"records": records},
        headers=headers,
    )
    r.raise_for_status()
    print(f"{len(records)} lignes insérées dans {table}")


# 1. Lire Tableau_recap_stage
rows = get_records("Tableau_recap_stage")
print(rows[43]["fields"])  # debug

# 2. Éclater la colonne Public
publics = []
for row in rows:
    id_stage = row["id"]
    valeurs = row["fields"].get("Public", "") or ""
    for val in valeurs.split(","):
        val = val.strip()
        if val:
            publics.append({"fields": {"id_stage": id_stage, "public": val}})
            if id_stage in [44, 45, 46, 47, 48, 49]:
                print(f"Ajouté : {id_stage} -> {repr(val)}")

# DEBUT DEBUG
for p in publics:
    print(p["fields"]["id_stage"], p["fields"]["public"])
# FIN DEBUG

print(f"{len(publics)} entrées éclatées")

# 3. Vider Publics
delete_all("Publics")

# 4. Réinsérer
if publics:
    insert_records("Publics", publics)
