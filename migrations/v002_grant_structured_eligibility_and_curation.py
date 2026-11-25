"""Migration 002: Grant structured eligibility columns, nationality rule, and Top 10 curation.

Adds Phase 2 columns on `grants`, creates composite index
`ix_grants_status_featured_deadline`, and deterministically backfills
verified structured conditions on existing seeded rows matched by `official_url`.
"""

import json
from typing import Any, Dict, List, Tuple
from sqlalchemy import Connection, inspect, text

VERSION = 2
DESCRIPTION = "Add structured eligibility columns, nationality_rule, featured_rank, and backfill"

NEW_COLUMNS: List[Tuple[str, str]] = [
    ("featured_rank", "INTEGER"),
    ("provider_name", "VARCHAR(255)"),
    ("host_country", "VARCHAR(64)"),
    ("allowed_degrees", "JSON"),
    ("min_gpa_value", "FLOAT"),
    ("min_gpa_scale", "VARCHAR(20)"),
    ("min_gpa_normalized_4", "FLOAT"),
    ("language_requirements", "JSON"),
    ("nationality_rule", "JSON"),
    ("min_work_years", "FLOAT"),
    ("max_age", "INTEGER"),
    ("funding_type", "VARCHAR(32)"),
]


def _json_param(val: Any) -> Any:
    if val is None:
        return None
    return json.dumps(val, ensure_ascii=False)


def _merge_json_map(existing_raw: Any, additions: Dict[str, str]) -> str:
    base: Dict[str, Any] = {}
    if isinstance(existing_raw, dict):
        base = dict(existing_raw)
    elif isinstance(existing_raw, str) and existing_raw.strip():
        try:
            loaded = json.loads(existing_raw)
            if isinstance(loaded, dict):
                base = loaded
        except json.JSONDecodeError:
            base = {}
    for k, v in additions.items():
        if k not in base and v is not None:
            base[k] = v
    return json.dumps(base, ensure_ascii=False)


def _backfill_seeded_grants(conn: Connection) -> None:
    """Populate structured fields on matching seeded grants using verified quotes only."""
    from seed.structured_backfill import build_verified_backfill_map

    backfill_map = build_verified_backfill_map()
    rows = conn.execute(
        text(
            "SELECT id, official_url, evidence, field_verification, "
            "provider_name, host_country, allowed_degrees, min_gpa_value, min_gpa_scale, "
            "min_gpa_normalized_4, language_requirements, nationality_rule, min_work_years, "
            "max_age, funding_type FROM grants"
        )
    ).mappings().all()

    for row in rows:
        record = backfill_map.get(row["official_url"])
        if not record:
            continue

        merged_evidence = _merge_json_map(row["evidence"], record.get("evidence_additions", {}))
        merged_verification = _merge_json_map(
            row["field_verification"], record.get("verification_additions", {})
        )

        conn.execute(
            text(
                """
                UPDATE grants
                SET
                    provider_name = COALESCE(provider_name, :provider_name),
                    host_country = COALESCE(host_country, :host_country),
                    allowed_degrees = COALESCE(allowed_degrees, :allowed_degrees),
                    min_gpa_value = COALESCE(min_gpa_value, :min_gpa_value),
                    min_gpa_scale = COALESCE(min_gpa_scale, :min_gpa_scale),
                    min_gpa_normalized_4 = COALESCE(min_gpa_normalized_4, :min_gpa_normalized_4),
                    language_requirements = COALESCE(language_requirements, :language_requirements),
                    nationality_rule = COALESCE(nationality_rule, :nationality_rule),
                    min_work_years = COALESCE(min_work_years, :min_work_years),
                    max_age = COALESCE(max_age, :max_age),
                    funding_type = COALESCE(funding_type, :funding_type),
                    evidence = :evidence,
                    field_verification = :field_verification
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "provider_name": record.get("provider_name"),
                "host_country": record.get("host_country"),
                "allowed_degrees": _json_param(record.get("allowed_degrees")),
                "min_gpa_value": record.get("min_gpa_value"),
                "min_gpa_scale": record.get("min_gpa_scale"),
                "min_gpa_normalized_4": record.get("min_gpa_normalized_4"),
                "language_requirements": _json_param(record.get("language_requirements")),
                "nationality_rule": _json_param(record.get("nationality_rule")),
                "min_work_years": record.get("min_work_years"),
                "max_age": record.get("max_age"),
                "funding_type": record.get("funding_type"),
                "evidence": merged_evidence,
                "field_verification": merged_verification,
            },
        )


def up(conn: Connection) -> None:
    inspector = inspect(conn)
    existing_cols = {col["name"] for col in inspector.get_columns("grants")}

    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing_cols:
            conn.execute(text(f"ALTER TABLE grants ADD COLUMN {col_name} {col_type}"))

    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_grants_status_featured_deadline "
            "ON grants (status, featured_rank, deadline)"
        )
    )

    _backfill_seeded_grants(conn)
