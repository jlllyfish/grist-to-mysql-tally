"""
main.py
Migration initiale multi-documents Grist → MySQL.
À lancer une seule fois par document.
"""

import logging
import sys

from config import Config
from grist_client import GristClient
from mysql_writer import MySQLWriter, create_mysql_engine
from reader import GristReader

logger = logging.getLogger(__name__)


def main():
    try:
        cfg = Config.from_env()
    except EnvironmentError as e:
        print(f"Erreur de configuration : {e}")
        sys.exit(1)

    cfg.setup_logging()
    logger.info("Démarrage migration\n%s", cfg.summary())

    engine = create_mysql_engine(
        host=cfg.mysql_host,
        port=cfg.mysql_port,
        user=cfg.mysql_user,
        password=cfg.mysql_password,
        database=cfg.mysql_database,
    )
    writer = MySQLWriter(engine)
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

        try:
            all_tables = reader.read_document(include_records=True)
        except Exception as e:
            logger.error("Échec lecture doc %s : %s", doc.doc_id, e)
            all_failed.append(doc.doc_id)
            continue

        tables = (
            [t for t in all_tables if t.id in doc.tables] if doc.tables else all_tables
        )

        missing = set(doc.tables) - {t.id for t in tables}
        if missing:
            logger.warning("Tables introuvables : %s", ", ".join(missing))

        logger.info("%d table(s) à migrer", len(tables))
        for t in tables:
            logger.info(
                "  %-30s %d colonnes  %d records", t.id, len(t.columns), len(t.records)
            )

        if cfg.dry_run:
            continue

        report = writer.write_document(tables)
        all_failed += [r.table_id for r in report.results if not r.success]

    if cfg.dry_run:
        logger.info("DRY RUN — rien écrit.")

    sys.exit(1 if all_failed else 0)


if __name__ == "__main__":
    main()
