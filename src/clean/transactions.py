"""Read the raw workbook, run the cleaning rules in order and write the cleaned outputs."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.clean import profile, rules
from src.config import SETTINGS_PATH, get, load_settings, resolve_path
from src.utils.logging import get_logger

CODE_GROUP_SETTINGS = {
    "shipping": "cleaning.shipping_codes",
    "adjustment": "cleaning.adjustment_codes",
    "test": "cleaning.test_codes",
}

log = get_logger(__name__)


def read_workbook(path: Path, sheets: Sequence[str]) -> pd.DataFrame:
    return pd.concat([pd.read_excel(path, sheet_name=sheet) for sheet in sheets], ignore_index=True)


def load_union(settings: dict[str, Any]) -> pd.DataFrame:
    """Normalise both sheets into one frame, reusing the interim cache while it is current."""
    workbook = resolve_path("raw") / get(settings, "dataset.raw_filename")
    cache = resolve_path("interim") / get(settings, "cleaning.union_cache_filename")

    # normalisation bakes in the settings, so a config edit has to invalidate the cache too
    source_mtime = max(workbook.stat().st_mtime, SETTINGS_PATH.stat().st_mtime)
    # the workbook takes minutes to parse, so only re-read it when something upstream changed
    if cache.exists() and cache.stat().st_mtime >= source_mtime:
        log.info("reusing the normalised union cached at %s", cache)
        return pd.read_parquet(cache)

    log.info("reading %s", workbook)
    union, rows = rules.normalise_columns(
        read_workbook(workbook, get(settings, "dataset.sheets")),
        get(settings, "cleaning.country_overrides"),
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    union.to_parquet(cache, index=False)
    log.info("normalised %s raw rows and cached them at %s", rows, cache)
    return union


def clean_transactions() -> dict[str, Any]:
    """Apply every rule in order, write the transactions, quarantine and DQ report."""
    settings = load_settings()
    duplicate_key = get(settings, "cleaning.duplicate_key")
    union = load_union(settings)

    frame, backfilled = rules.backfill_description(union)
    frame, deduped = rules.drop_exact_duplicates(frame, duplicate_key)
    frame, cancellations = rules.flag_cancellations(
        frame, get(settings, "cleaning.cancellation_prefix")
    )
    frame, non_product = rules.classify_line_type(
        frame, {group: get(settings, key) for group, key in CODE_GROUP_SETTINGS.items()}
    )
    frame, guests = rules.count_guest_lines(frame)
    kept, quarantined = rules.quarantine_invalid_economics(
        frame, get(settings, "cleaning.min_unit_price")
    )
    rules.reconcile(len(union), len(kept), deduped, len(quarantined))

    kept = rules.order_for_output(kept, duplicate_key)
    quarantined = rules.order_for_output(quarantined, duplicate_key)
    kept.to_parquet(
        resolve_path("processed") / get(settings, "cleaning.transactions_filename"), index=False
    )
    quarantined.to_parquet(
        resolve_path("quarantine") / get(settings, "cleaning.quarantine_filename"), index=False
    )

    report = profile.build_dq_report(
        kept,
        quarantined,
        {
            "raw_rows": len(union),
            "kept_rows": len(kept),
            "deduped_rows": deduped,
            "quarantined_rows": len(quarantined),
        },
        {
            "descriptions_backfilled": backfilled,
            "cancellations_flagged": cancellations,
            "non_product_lines": non_product,
            "guest_lines": guests,
        },
        get(settings, "cleaning.net_revenue_line_types"),
        float(union["line_revenue"].sum()),
    )
    profile.write_dq_report(
        report, resolve_path("processed") / get(settings, "cleaning.dq_report_filename")
    )

    log.info(
        "kept %s rows, deduped %s, quarantined %s, net revenue %.2f",
        len(kept),
        deduped,
        len(quarantined),
        report["revenue"]["net"],
    )
    return report
