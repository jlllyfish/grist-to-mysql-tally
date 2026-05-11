"""
sync.py
Synchronisation quotidienne Grist → MySQL avec upsert + suppression.
"""

import logging
import sys
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from grist_client import GristClient
from reader import GristReader
from mysql_writer import create_mysql_engine
from mapper import cast_value
from mysql_writer import _safe_col_name

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Clé métier par table                                                 #
# ------------------------------------------------------------------ #

KEY_COLUMNS: dict[str, str] = {
    "Tally_old": "submission_id",
    "Retours_Tally_new": "submission_id",
    "Users_instance_dev": "id_bdd",
    "Formulaire_contact_OTP": "Email",
    "Tableau_recap_stage": "id_stage",
    "Publics": "UUID",
}


# ------------------------------------------------------------------ #
# Rapport                                                              #
# ------------------------------------------------------------------ #

@dataclass
class TableSyncResult:
    table_id: str
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    def log(self):
        status = "✅" if self.success else "❌"
        parts = []
        if self.inserted: parts.append(f"🟢 +{self.inserted} insérés")
        if self.updated:  parts.append(f"🔵 ~{self.updated} modifiés")
        if self.deleted:  parts.append(f"🔴 -{self.deleted} supprimés")
        if self.skipped:  parts.append(f"⚪ ={self.skipped} inchangés")
        summary = "  ".join(parts) if parts else "⚪ aucun changement"
        logger.info("%s  %-30s  %s", status, self.table_id, summary)
        for err in self.errors:
            logger.error("   ⚠️  %s", err)


@dataclass
class SyncReport:
    results: list[TableSyncResult] = field(default_factory=list)

    def log_summary(self):
        logger.info("=" * 60)
        logger.info("RAPPORT DE SYNC  (+insérés  ~modifiés  -supprimés  =inchangés)")
        logger.info("-" * 60)
        for r in self.results:
            r.log()
        logger.info("-" * 60)
        logger.info(
            "TOTAL  +%d  ~%d  -%d  =%d",
            sum(r.inserted for r in self.results),
            sum(r.updated for r in self.results),
            sum(r.deleted for r in self.results),
            sum(r.skipped for r in self.results),
        )
        logger.info("=" * 60)


# ------------------------------------------------------------------ #
# Syncer                                                               #
# ------------------------------------------------------------------ #

class GristMySQLSyncer:
    CHUNK_SIZE = 500

    def __init__(self, reader: GristReader, engine):
        self.reader = reader
        self.engine = engine

    def sync_all(self, tables_to_sync: tuple) -> SyncReport:
        report = SyncReport()
        all_tables = self.reader.read_document(include_records=True)

        tables = (
            [t for t in all_tables if t.id in tables_to_sync]
            if tables_to_sync else all_tables
        )

        for table in tables:
            key_col = KEY_COLUMNS.get(table.id)
            if not key_col:
                logger.warning("Table %s ignorée : aucune clé dans KEY_COLUMNS", table.id)
                continue
            result = self._sync_table(table, key_col)
            report.results.append(result)

        report.log_summary()
        return report

    def _sync_table(self, table, key_col: str) -> TableSyncResult:
        result = TableSyncResult(table_id=table.id)
        col_types = {col.id: col.type for col in table.columns}
        safe_key_col = _safe_col_name(key_col)

        # Index source par clé métier
        source_index = {
            rec["fields"].get(key_col): rec
            for rec in table.records
            if rec["fields"].get(key_col) is not None
        }

        # Index cible depuis MySQL
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(f"SELECT grist_id, `{safe_key_col}` FROM `{table.id}`")
                ).fetchall()
            target_index = {row[1]: row[0] for row in rows}  # {key_value: grist_id}
        except SQLAlchemyError as e:
            result.errors.append(f"Lecture MySQL échouée : {e}")
            return result

        to_insert, to_update, to_delete = [], [], []

        # Détecter et ajouter les nouvelles colonnes Grist absentes de MySQL
        try:
            with self.engine.connect() as conn:
                existing_cols = {
                    row[0]
                    for row in conn.execute(text(f"SHOW COLUMNS FROM `{table.id}`")).fetchall()
                }
            for col in table.columns:
                safe = _safe_col_name(col.id)
                if safe not in existing_cols:
                    from mapper import grist_type_to_sqla
                    sqla_col = grist_type_to_sqla(col.type, safe)
                    col_type_sql = str(sqla_col.type.compile(dialect=self.engine.dialect))
                    with self.engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE `{table.id}` ADD COLUMN `{safe}` {col_type_sql}"))
                    logger.info("🆕 Colonne ajoutée : %s.%s", table.id, safe)
        except SQLAlchemyError as e:
            logger.warning("Détection nouvelles colonnes échouée pour %s : %s", table.id, e)

        # Charger tous les champs cible pour comparaison
        try:
            with self.engine.connect() as conn:
                all_rows = conn.execute(text(f"SELECT * FROM `{table.id}`")).mappings().fetchall()
            target_fields_by_grist_id = {row["grist_id"]: dict(row) for row in all_rows}
        except SQLAlchemyError as e:
            result.errors.append(f"Lecture champs MySQL échouée : {e}")
            return result

        for key, src_rec in source_index.items():
            fields = {
                _safe_col_name(k): cast_value(v, col_types.get(k, "Text"))
                for k, v in src_rec["fields"].items()
            }
            if key not in target_index:
                to_insert.append({"grist_id": src_rec["id"], **fields})
            else:
                grist_id = src_rec["id"]
                tgt = target_fields_by_grist_id.get(grist_id, {})
                diff = {k: v for k, v in fields.items() if str(tgt.get(k, "")) != str(v) if v is not None}
                if diff:
                    to_update.append({"grist_id": grist_id, **diff})
                else:
                    result.skipped += 1

        for key, grist_id in target_index.items():
            if key not in source_index:
                to_delete.append(grist_id)

        # Exécution
        with self.engine.begin() as conn:
            if to_insert:
                try:
                    cols = list(to_insert[0].keys())
                    col_str = ", ".join(f"`{c}`" for c in cols)
                    val_str = ", ".join(f":{c}" for c in cols)
                    sql = f"INSERT INTO `{table.id}` ({col_str}) VALUES ({val_str})"
                    for chunk in self._chunks(to_insert):
                        conn.execute(text(sql), chunk)
                    result.inserted = len(to_insert)
                except SQLAlchemyError as e:
                    result.errors.append(f"Insert échoué : {e}")

            if to_update:
                try:
                    for rec in to_update:
                        cols = [c for c in rec.keys() if c != "grist_id"]
                        set_str = ", ".join(f"`{c}` = :{c}" for c in cols)
                        sql = f"UPDATE `{table.id}` SET {set_str} WHERE grist_id = :grist_id"
                        conn.execute(text(sql), rec)
                    result.updated = len(to_update)
                except SQLAlchemyError as e:
                    result.errors.append(f"Update échoué : {e}")

            if to_delete:
                try:
                    for chunk in self._chunks(to_delete):
                        ids = ", ".join(str(i) for i in chunk)
                        conn.execute(text(f"DELETE FROM `{table.id}` WHERE grist_id IN ({ids})"))
                    result.deleted = len(to_delete)
                except SQLAlchemyError as e:
                    result.errors.append(f"Delete échoué : {e}")

        # skipped est incrémenté au fil de la comparaison
        return result

    def _chunks(self, items, size=None):
        size = size or self.CHUNK_SIZE
        for i in range(0, len(items), size):
            yield items[i: i + size]


# ------------------------------------------------------------------ #
# Point d'entrée                                                       #
# ------------------------------------------------------------------ #

def main():
    if not KEY_COLUMNS:
        print(
            "⚠  KEY_COLUMNS est vide dans sync.py\n"
            "   Renseigne la clé métier de chaque table avant de lancer la sync."
        )
        sys.exit(1)

    try:
        cfg = Config.from_env()
    except EnvironmentError as e:
        print(f"Erreur de configuration : {e}")
        sys.exit(1)

    cfg.setup_logging()
    logger.info("Démarrage sync\n%s", cfg.summary())

    engine = create_mysql_engine(
        host=cfg.mysql_host,
        port=cfg.mysql_port,
        user=cfg.mysql_user,
        password=cfg.mysql_password,
        database=cfg.mysql_database,
    )

    all_failed = []
    for i, doc in enumerate(cfg.docs, 1):
        logger.info("━" * 50)
        logger.info("📄 Document %d : %s", i, doc.doc_id)

        client = GristClient(
            api_key=cfg.grist_api_key,
            server=cfg.grist_server,
            doc_id=doc.doc_id,
        )
        reader = GristReader(client)
        syncer = GristMySQLSyncer(reader, engine)
        report = syncer.sync_all(doc.tables)
        all_failed += [r for r in report.results if not r.success]

    sys.exit(1 if all_failed else 0)


if __name__ == "__main__":
    main()
