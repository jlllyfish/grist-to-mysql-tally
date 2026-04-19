"""
config.py
Configuration Grist source + MySQL cible.
"""

import os
import logging
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variable d'environnement manquante : {key}")
    return value


@dataclass(frozen=True)
class Config:
    # Grist source
    grist_api_key: str
    grist_server: str
    grist_doc_id: str
    tables_to_sync: tuple          # tuple de noms de tables (vide = toutes)

    # MySQL cible
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
        tables_raw = os.getenv("TABLES_TO_SYNC", "")
        tables = tuple(t.strip() for t in tables_raw.split(",") if t.strip())

        return cls(
            grist_api_key=_require("GRIST_API_KEY"),
            grist_server=os.getenv("GRIST_SERVER", "https://docs.getgrist.com"),
            grist_doc_id=_require("GRIST_DOC_ID"),
            tables_to_sync=tables,

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
        tables_info = ", ".join(self.tables_to_sync) if self.tables_to_sync else "toutes"
        return (
            f"Grist  : {self.grist_server} / doc={self.grist_doc_id}\n"
            f"MySQL  : {self.mysql_user}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}\n"
            f"Tables : {tables_info}\n"
            f"DRY_RUN={self.dry_run}"
        )
