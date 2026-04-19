"""
main.py
Migration initiale : lit les tables Grist et les crée dans MySQL avec leurs données.
À lancer une seule fois.
"""

import logging
import sys

from config import Config
from grist_client import GristClient
from reader import GristReader
from mysql_writer import MySQLWriter, create_mysql_engine

logger = logging.getLogger(__name__)


def main():
    try:
        cfg = Config.from_env()
    except EnvironmentError as e:
        print(f"Erreur de configuration : {e}")
        sys.exit(1)

    cfg.setup_logging()
    logger.info("Démarrage migration\n%s", cfg.summary())

    # --- Lecture Grist -------------------------------------------
    client = GristClient(
        api_key=cfg.grist_api_key,
        server=cfg.grist_server,
        doc_id=cfg.grist_doc_id,
    )
    reader = GristReader(client)

    logger.info("Lecture du document Grist...")
    try:
        all_tables = reader.read_document(include_records=True)
    except Exception as e:
        logger.error("Échec lecture Grist : %s", e)
        sys.exit(1)

    # Filtrer sur TABLES_TO_SYNC si défini
    if cfg.tables_to_sync:
        tables = [t for t in all_tables if t.id in cfg.tables_to_sync]
        missing = set(cfg.tables_to_sync) - {t.id for t in tables}
        if missing:
            logger.warning("Tables introuvables dans Grist : %s", ", ".join(missing))
    else:
        tables = all_tables

    logger.info("%d table(s) à migrer", len(tables))
    for t in tables:
        logger.info("  %-30s %d colonnes  %d records", t.id, len(t.columns), len(t.records))

    if cfg.dry_run:
        logger.info("DRY RUN — rien écrit.")
        sys.exit(0)

    # --- Écriture MySQL ------------------------------------------
    engine = create_mysql_engine(
        host=cfg.mysql_host,
        port=cfg.mysql_port,
        user=cfg.mysql_user,
        password=cfg.mysql_password,
        database=cfg.mysql_database,
    )
    writer = MySQLWriter(engine)

    try:
        report = writer.write_document(tables)
    except Exception as e:
        logger.error("Échec écriture MySQL : %s", e)
        sys.exit(1)

    failed = [r for r in report.results if not r.success]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
