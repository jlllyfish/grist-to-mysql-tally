"""
mysql_writer.py
Création des tables MySQL depuis la structure Grist et import des records.
"""

import logging
from dataclasses import dataclass, field

from mapper import cast_value, grist_type_to_sqla
from reader import TableInfo
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

MYSQL_MAX_IDENTIFIER = 64


def _safe_col_name(name: str) -> str:
    """Tronque un nom de colonne à 64 caractères (limite MySQL)."""
    return name[:MYSQL_MAX_IDENTIFIER]


# ------------------------------------------------------------------ #
# Rapport                                                              #
# ------------------------------------------------------------------ #


@dataclass
class TableWriteResult:
    table_id: str
    created: bool = False
    records_total: int = 0
    records_imported: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


@dataclass
class WriteReport:
    results: list[TableWriteResult] = field(default_factory=list)

    def log_summary(self):
        total = sum(r.records_total for r in self.results)
        imported = sum(r.records_imported for r in self.results)
        failed = [r.table_id for r in self.results if not r.success]
        logger.info("=" * 50)
        logger.info("RAPPORT D'IMPORT MYSQL")
        logger.info(
            "Tables : %d | Records : %d / %d", len(self.results), imported, total
        )
        if failed:
            logger.warning("Tables en erreur : %s", ", ".join(failed))
        else:
            logger.info("Import terminé avec succès ✓")
        logger.info("=" * 50)


# ------------------------------------------------------------------ #
# Writer                                                               #
# ------------------------------------------------------------------ #


class MySQLWriter:
    CHUNK_SIZE = 500

    def __init__(self, engine: Engine):
        self.engine = engine
        self.metadata = MetaData()

    # -- Création de table ----------------------------------------- #

    def create_table(self, table: TableInfo) -> TableWriteResult:
        result = TableWriteResult(table_id=table.id, records_total=len(table.records))

        inspector = inspect(self.engine)
        if inspector.has_table(table.id):
            logger.info("Table %s déjà existante — ignorée", table.id)
            result.created = False
            return result

        columns = [
            Column(
                "grist_id",
                Integer,
                primary_key=True,
                autoincrement=False,
                comment="rowId Grist original",
            ),
            *[
                grist_type_to_sqla(col.type, _safe_col_name(col.id))
                for col in table.columns
            ],
        ]

        sqla_table = Table(table.id, self.metadata, *columns)
        try:
            self.metadata.create_all(self.engine, tables=[sqla_table])
            result.created = True
            logger.info("Table créée : %s (%d colonnes)", table.id, len(columns) - 1)
        except SQLAlchemyError as e:
            msg = f"Création table {table.id} échouée : {e}"
            logger.error(msg)
            result.errors.append(msg)

        return result

    # -- Import records -------------------------------------------- #

    def import_records(self, table: TableInfo, result: TableWriteResult) -> None:
        if not table.records:
            logger.info("Table %s : aucun record", table.id)
            return

        col_types = {col.id: col.type for col in table.columns}
        rows = []
        for rec in table.records:
            row = {"grist_id": rec["id"]}
            for col_id, value in rec["fields"].items():
                grist_type = col_types.get(col_id, "Text")
                row[_safe_col_name(col_id)] = cast_value(value, grist_type)
            rows.append(row)

        try:
            with self.engine.begin() as conn:
                for chunk in self._chunks(rows):
                    conn.execute(
                        text(self._build_insert(table.id, list(rows[0].keys()))),
                        chunk,
                    )
            result.records_imported = len(rows)
            logger.info("Table %s : %d records importés", table.id, len(rows))
        except SQLAlchemyError as e:
            msg = f"Import records {table.id} échoué : {e}"
            logger.error(msg)
            result.errors.append(msg)

    def _build_insert(self, table_id: str, columns: list[str]) -> str:
        cols = ", ".join(f"`{c}`" for c in columns)
        vals = ", ".join(f":{c}" for c in columns)
        return f"INSERT INTO `{table_id}` ({cols}) VALUES ({vals})"

    # -- Orchestration --------------------------------------------- #

    def write_document(self, tables: list[TableInfo]) -> WriteReport:
        report = WriteReport()

        for table in tables:
            result = self.create_table(table)
            if result.created:
                self.import_records(table, result)
            report.results.append(result)

        report.log_summary()
        return report

    # -- Helpers --------------------------------------------------- #

    def _chunks(self, items: list, size: int | None = None):
        size = size or self.CHUNK_SIZE
        for i in range(0, len(items), size):
            yield items[i : i + size]


# ------------------------------------------------------------------ #
# Factory                                                              #
# ------------------------------------------------------------------ #


def create_mysql_engine(
    host: str, port: int, user: str, password: str, database: str
) -> Engine:
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
    engine = create_engine(url, echo=False, pool_pre_ping=True)
    logger.info("Connexion MySQL : %s@%s:%s/%s", user, host, port, database)
    return engine
