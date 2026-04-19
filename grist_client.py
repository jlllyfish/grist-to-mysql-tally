"""
grist_client.py
Wrapper HTTP pour l'API Grist avec auth, retry et pagination.
"""

import os
import time
import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class GristAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"[{status_code}] {message}")


class GristClient:
    CHUNK_SIZE = 500

    def __init__(
        self,
        api_key: str | None = None,
        server: str | None = None,
        doc_id: str | None = None,
    ):
        self.api_key = api_key or os.environ["GRIST_API_KEY"]
        self.server = (server or os.environ.get("GRIST_SERVER", "https://docs.getgrist.com")).rstrip("/")
        self.doc_id = doc_id or os.environ["GRIST_DOC_ID"]
        self._session = self._build_session()

    # ------------------------------------------------------------------ #
    # Session                                                              #
    # ------------------------------------------------------------------ #

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })
        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PATCH", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # ------------------------------------------------------------------ #
    # HTTP helpers                                                         #
    # ------------------------------------------------------------------ #

    def _url(self, path: str) -> str:
        return f"{self.server}/api/docs/{self.doc_id}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self._url(path)
        logger.debug("%s %s", method, url)
        resp = self._session.request(method, url, timeout=30, **kwargs)
        if not resp.ok:
            raise GristAPIError(resp.status_code, resp.text)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, payload: Any) -> Any:
        return self._request("POST", path, json=payload)

    def patch(self, path: str, payload: Any) -> Any:
        return self._request("PATCH", path, json=payload)

    def delete(self, path: str, payload: Any | None = None) -> Any:
        return self._request("DELETE", path, json=payload)

    # ------------------------------------------------------------------ #
    # Tables                                                               #
    # ------------------------------------------------------------------ #

    def list_tables(self) -> list[dict]:
        """Retourne la liste brute des tables du document."""
        data = self.get("tables")
        return data.get("tables", [])

    def create_table(self, table_id: str, columns: list[dict]) -> dict:
        """
        Crée une table avec ses colonnes.
        columns : liste de dicts {"id": str, "fields": {"label": str, "type": str, ...}}
        """
        payload = {"tables": [{"id": table_id, "columns": columns}]}
        return self.post("tables", payload)

    # ------------------------------------------------------------------ #
    # Colonnes                                                             #
    # ------------------------------------------------------------------ #

    def list_columns(self, table_id: str) -> list[dict]:
        """Retourne la liste brute des colonnes d'une table."""
        data = self.get(f"tables/{table_id}/columns")
        return data.get("columns", [])

    def add_columns(self, table_id: str, columns: list[dict]) -> dict:
        """
        Ajoute des colonnes à une table existante.
        columns : liste de dicts {"id": str, "fields": {...}}
        """
        payload = {"columns": columns}
        return self.post(f"tables/{table_id}/columns", payload)

    # ------------------------------------------------------------------ #
    # Records                                                              #
    # ------------------------------------------------------------------ #

    def list_records(self, table_id: str) -> list[dict]:
        """Retourne tous les records d'une table (liste de dicts {id, fields})."""
        data = self.get(f"tables/{table_id}/records")
        return data.get("records", [])

    def add_records(self, table_id: str, records: list[dict]) -> list[int]:
        """
        Insère des records par chunks.
        records : liste de dicts {"fields": {col_id: value, ...}}
        Retourne la liste des rowIds créés.
        """
        row_ids: list[int] = []
        for chunk in self._chunks(records):
            result = self.post(f"tables/{table_id}/records", {"records": chunk})
            row_ids.extend(result.get("records", []))
            time.sleep(0.1)  # politesse envers l'API
        return row_ids

    # ------------------------------------------------------------------ #
    # Utilitaires                                                          #
    # ------------------------------------------------------------------ #

    def _chunks(self, items: list, size: int | None = None):
        size = size or self.CHUNK_SIZE
        for i in range(0, len(items), size):
            yield items[i: i + size]
