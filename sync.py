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

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Clé métier par table                                                 #
# ------------------------------------------------------------------ #

KEY_COLUMNS: dict[str, str] = {
    "Tally_old": "submission_id",
    "Retours_Tally_new": "submission_id",
    "Users_instance_dev": "id",
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
        logger.info(
            "%-30s  +%d  ~%d  -%d  =%d%s",
            self.table_id, self.inserted, self.updated,
            self.deleted, self.skipped,
            f"  ⚠ {len(self.errors)} erreur(s)" if self.errors else "",
        )


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
                    text(f"SELECT grist_id, `{key_col}` FROM `{table.id}`")
                ).fetchall()
            target_index = {row[1]: row[0] for row in rows}  # {key_value: grist_id}
        except SQLAlchemyError as e:
            result.errors.append(f"Lecture MySQL échouée : {e}")
            return result

        to_insert, to_update, to_delete = [], [], []

        for key, src_rec in source_index.items():
            fields = {
                k: cast_value(v, col_types.get(k, "Text"))
                for k, v in src_rec["fields"].items()
            }
            if key not in target_index:
                to_insert.append({"grist_id": src_rec["id"], **fields})
            else:
                to_update.append({"grist_id": src_rec["id"], **fields})

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
                    cols = [c for c in to_update[0].keys() if c != "grist_id"]
                    set_str = ", ".join(f"`{c}` = :{c}" for c in cols)
                    sql = f"UPDATE `{table.id}` SET {set_str} WHERE grist_id = :grist_id"
                    for chunk in self._chunks(to_update):
                        conn.execute(text(sql), chunk)
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

        result.skipped = len(source_index) - len(to_insert) - len(to_update)
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

    client = GristClient(
        api_key=cfg.grist_api_key,
        server=cfg.grist_server,
        doc_id=cfg.grist_doc_id,
    )
    reader = GristReader(client)
    engine = create_mysql_engine(
        host=cfg.mysql_host,
        port=cfg.mysql_port,
        user=cfg.mysql_user,
        password=cfg.mysql_password,
        database=cfg.mysql_database,
    )

    syncer = GristMySQLSyncer(reader, engine)
    report = syncer.sync_all(cfg.tables_to_sync)

    failed = [r for r in report.results if not r.success]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
