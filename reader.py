"""
reader.py
Lecture et filtrage des tables, colonnes et records d'un document Grist source.
"""

import logging
from dataclasses import dataclass, field

from grist_client import GristClient

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Filtres                                                              #
# ------------------------------------------------------------------ #

EXCLUDED_TABLE_PREFIXES = ("_grist_",)

EXCLUDED_COLUMNS = {"manualSort", "id"}
EXCLUDED_COLUMN_PREFIXES = ("gristHelper_",)
EXCLUDED_COLUMN_TYPES = {"Attachments"}


def _is_user_table(table: dict) -> bool:
    tid = table["id"]
    is_hidden = table.get("isHidden", False)
    return not is_hidden and not any(tid.startswith(p) for p in EXCLUDED_TABLE_PREFIXES)


def _is_user_column(col: dict) -> bool:
    cid = col["id"]
    ctype = col.get("fields", {}).get("type", "")
    return (
        cid not in EXCLUDED_COLUMNS
        and not any(cid.startswith(p) for p in EXCLUDED_COLUMN_PREFIXES)
        and ctype not in EXCLUDED_COLUMN_TYPES
    )


# ------------------------------------------------------------------ #
# Structures de données                                                #
# ------------------------------------------------------------------ #


@dataclass
class ColumnInfo:
    id: str
    label: str
    type: str
    widget_options: dict = field(default_factory=dict)
    formula: str = ""
    is_formula: bool = False

    def to_api_payload(self) -> dict:
        """Format attendu par POST /columns."""
        fields: dict = {
            "label": self.label,
            "type": self.type,
        }
        if self.widget_options:
            fields["widgetOptions"] = self.widget_options
        # On n'exporte pas les formules : elles peuvent référencer
        # d'autres tables/colonnes qui n'existent pas encore.
        return {"id": self.id, "fields": fields}


@dataclass
class TableInfo:
    id: str
    label: str
    columns: list[ColumnInfo] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)


# ------------------------------------------------------------------ #
# Reader                                                               #
# ------------------------------------------------------------------ #


class GristReader:
    def __init__(self, client: GristClient):
        self.client = client

    # -- Tables ---------------------------------------------------- #

    def get_user_tables(self) -> list[dict]:
        """Retourne les tables utilisateur (hors tables techniques Grist)."""
        all_tables = self.client.list_tables()
        user_tables = [t for t in all_tables if _is_user_table(t)]
        excluded = len(all_tables) - len(user_tables)
        logger.info(
            "Tables : %d total, %d utilisateur, %d exclues",
            len(all_tables),
            len(user_tables),
            excluded,
        )
        return user_tables

    # -- Colonnes -------------------------------------------------- #

    def get_user_columns(self, table_id: str) -> list[ColumnInfo]:
        """Retourne les colonnes utilisateur d'une table."""
        all_cols = self.client.list_columns(table_id)
        user_cols = [c for c in all_cols if _is_user_column(c)]
        logger.debug(
            "Table %s : %d colonnes total, %d utilisateur",
            table_id,
            len(all_cols),
            len(user_cols),
        )
        return [self._parse_column(c) for c in user_cols]

    def _parse_column(self, raw: dict) -> ColumnInfo:
        f = raw.get("fields", {})
        return ColumnInfo(
            id=raw["id"],
            label=f.get("label", raw["id"]),
            type=f.get("type", "Text"),
            widget_options=f.get("widgetOptions") or {},
            formula=f.get("formula", ""),
            is_formula=bool(f.get("isFormula", False)),
        )

    # -- Records --------------------------------------------------- #

    def get_records(self, table_id: str, columns: list[ColumnInfo]) -> list[dict]:
        """
        Retourne les records filtrés sur les colonnes utilisateur uniquement.
        Chaque record : {"id": int, "fields": {col_id: value, ...}}
        """
        raw_records = self.client.list_records(table_id)
        col_ids = {c.id for c in columns if not c.is_formula}

        cleaned = []
        for rec in raw_records:
            fields = {k: v for k, v in rec.get("fields", {}).items() if k in col_ids}
            cleaned.append({"id": rec["id"], "fields": fields})

        logger.info("Table %s : %d records lus", table_id, len(cleaned))
        return cleaned

    # -- Lecture complète ------------------------------------------ #

    def read_document(self, include_records: bool = True) -> list[TableInfo]:
        """
        Point d'entrée principal.
        Retourne la liste complète des TableInfo (structure + données).
        """
        tables = self.get_user_tables()
        result: list[TableInfo] = []

        for t in tables:
            tid = t["id"]
            label = t.get("fields", {}).get("tableId", tid)
            logger.info("Lecture table : %s", tid)

            columns = self.get_user_columns(tid)
            records = self.get_records(tid, columns) if include_records else []

            result.append(
                TableInfo(
                    id=tid,
                    label=label,
                    columns=columns,
                    records=records,
                )
            )

        return result
