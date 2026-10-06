import argparse
from collections.abc import Callable

from src.audit.workbook import build_audit_workbook
from src.clean.transactions import clean_transactions
from src.config import ensure_directories
from src.ingest.download import download_dataset
from src.utils.logging import configure_logging, get_logger


def run_ingest() -> None:
    ensure_directories()
    download_dataset()


def run_audit() -> None:
    ensure_directories()
    build_audit_workbook()


def run_clean() -> None:
    ensure_directories()
    clean_transactions()


def run_warehouse() -> None:
    raise NotImplementedError("warehouse stage is not built yet")


def run_all() -> None:
    for stage in (run_ingest, run_audit, run_clean, run_warehouse):
        stage()


STAGES: dict[str, tuple[Callable[[], None], str]] = {
    "ingest": (run_ingest, "download the Kaggle dataset into data/raw"),
    "audit": (run_audit, "profile the raw workbook into excel/data_audit.xlsx"),
    "clean": (run_clean, "apply cleaning rules, write the DQ report and quarantine"),
    "warehouse": (run_warehouse, "build the star schema and marts, export parquet"),
    "all": (run_all, "run ingest, audit, clean and warehouse in order"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="E-commerce revenue and customer intelligence pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="stages:\n"
        + "\n".join(f"  {name:<10}{help_text}" for name, (_, help_text) in STAGES.items()),
    )
    parser.add_argument("stage", choices=list(STAGES), metavar="stage", help="stage to run")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="override the level in config/settings.yml",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    log = get_logger(__name__)
    try:
        STAGES[args.stage][0]()
    except NotImplementedError as error:
        log.error("%s: %s", args.stage, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
