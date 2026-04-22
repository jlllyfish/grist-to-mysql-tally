"""
mapper.py
Conversion des types Grist → types SQLAlchemy pour la création des tables MySQL.
"""

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text

# ------------------------------------------------------------------ #
# Mapping Grist type → SQLAlchemy Column                              #
# ------------------------------------------------------------------ #


def grist_type_to_sqla(grist_type: str, col_id: str) -> Column:
    """
    Convertit un type Grist en colonne SQLAlchemy.
    grist_type peut être : "Text", "Numeric", "Int", "Bool",
    "Date", "DateTime", "Choice", "ChoiceList",
    "Ref:TableName", "RefList:TableName", "Any", ...
    """
    base_type = grist_type.split(":")[0]  # retire la partie ":TableName" des Ref

    mapping = {
        "Text": lambda: Column(col_id, Text),
        "Numeric": lambda: Column(col_id, Float),
        "Int": lambda: Column(col_id, Integer),
        "Bool": lambda: Column(col_id, Boolean),
        "Date": lambda: Column(col_id, Date),
        "DateTime": lambda: Column(col_id, DateTime),
        "Choice": lambda: Column(col_id, String(255)),
        "ChoiceList": lambda: Column(col_id, Text),
        "Ref": lambda: Column(col_id, Integer),  # rowId de la table référencée
        "RefList": lambda: Column(col_id, Text),  # liste de rowIds (JSON string)
        "Attachments": lambda: Column(col_id, Text),
        "Any": lambda: Column(col_id, Text),
    }

    factory = mapping.get(base_type, lambda: Column(col_id, Text))
    return factory()


# ------------------------------------------------------------------ #
# Conversion des valeurs                                               #
# ------------------------------------------------------------------ #


def cast_value(value, grist_type: str):
    """
    Nettoie/convertit une valeur Grist avant insertion MySQL.
    Gère notamment les listes encodées par Grist sous forme ["L", v1, v2, ...]
    """
    if value is None:
        return None

    base_type = grist_type.split(":")[0]

    # Grist encode les listes comme ["L", item1, item2, ...]
    if isinstance(value, list) and value and value[0] == "L":
        value = value[1:]

    if base_type in ("ChoiceList", "RefList", "Attachments"):
        import json

        lst = value if isinstance(value, list) else [value]
        return json.dumps(lst, ensure_ascii=False)

    if base_type == "Bool":
        return bool(value)

    if base_type == "Int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if base_type == "Numeric":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # Date/DateTime : Grist stocke en timestamp Unix (secondes)
    if base_type in ("Date", "DateTime"):
        if isinstance(value, (int, float)):
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.date() if base_type == "Date" else dt.replace(tzinfo=None)
        return None

    return value
