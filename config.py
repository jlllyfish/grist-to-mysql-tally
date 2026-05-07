"""
config.py
Configuration multi-documents Grist + MySQL cible.
"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variable d'environnement manquante : {key}")
    return value


def _parse_tables(raw: str) -> tuple:
    return tuple(t.strip() for t in raw.split(",") if t.strip())


@dataclass(frozen=True)
class GristDoc:
    doc_id: str
    tables: tuple  # vide = toutes


@dataclass(frozen=True)
class Config:
    # Grist
    grist_api_key: str
    grist_server: str
    docs: tuple  # tuple de GristDoc

    # MySQL
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str

    # Comportement
    dry_run: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        docs = []
        i = 1
        while True:
            doc_id = os.getenv(f"GRIST_DOC_{i}_ID")
            if not doc_id:
                break
            tables_raw = os.getenv(f"GRIST_DOC_{i}_TABLES", "")
            docs.append(
                GristDoc(
                    doc_id=doc_id,
                    tables=_parse_tables(tables_raw),
                )
            )
            i += 1

        # Rétrocompatibilité : GRIST_DOC_ID + TABLES_TO_SYNC
        if not docs:
            doc_id = os.getenv("GRIST_DOC_ID")
            if doc_id:
                tables_raw = os.getenv("TABLES_TO_SYNC", "")
                docs.append(
                    GristDoc(
                        doc_id=doc_id,
                        tables=_parse_tables(tables_raw),
                    )
                )

        if not docs:
            raise EnvironmentError(
                "Aucun document Grist configuré (GRIST_DOC_1_ID manquant)"
            )

        return cls(
            grist_api_key=_require("GRIST_API_KEY"),
            grist_server=os.getenv("GRIST_SERVER", "https://docs.getgrist.com"),
            docs=tuple(docs),
            mysql_host=os.getenv("MYSQL_HOST", "localhost"),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_user=_require("MYSQL_USER"),
            mysql_password=_require("MYSQL_PASSWORD"),
            mysql_database=_require("MYSQL_DATABASE"),
            dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def setup_logging(self):
        logging.basicConfig(
            level=getattr(logging, self.log_level, logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s : %(message)s",
            datefmt="%H:%M:%S",
        )

    def summary(self) -> str:
        lines = [
            f"MySQL  : {self.mysql_user}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        ]
        for i, doc in enumerate(self.docs, 1):
            tables = ", ".join(doc.tables) if doc.tables else "toutes"
            lines.append(f"Doc {i} : {self.grist_server} / {doc.doc_id} → {tables}")
        lines.append(f"DRY_RUN={self.dry_run}")
        return "\n".join(lines)
