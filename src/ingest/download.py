import hashlib
import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from src.config import get, load_settings, require_env, resolve_path
from src.utils.logging import get_logger

CHUNK_BYTES = 1024 * 1024
STDERR_TAIL_CHARS = 500
# kaggle 1.6 has no __main__
KAGGLE_CLI = "import sys; from kaggle.cli import main; sys.exit(main())"

log = get_logger(__name__)


def scrub_secrets(text: str, secrets: Iterable[str]) -> str:
    """Mask credential values so child output is safe to log or raise."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum_log(files: Iterable[Path], path: Path) -> dict[str, dict[str, object]]:
    downloaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries = {
        file.name: {
            "sha256": file_checksum(file),
            "bytes": file.stat().st_size,
            "downloaded_at": downloaded_at,
        }
        for file in files
    }
    path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return entries


def download_dataset(force: bool = False) -> Path:
    settings = load_settings()
    slug = get(settings, "dataset.slug")
    raw_dir = resolve_path("raw")
    target = raw_dir / get(settings, "dataset.raw_filename")

    if target.exists() and not force:
        log.info("skipping download, %s already in %s", target.name, raw_dir)
        return target

    username = require_env("KAGGLE_USERNAME")
    key = require_env("KAGGLE_KEY")
    child_env = {**os.environ, "KAGGLE_USERNAME": username, "KAGGLE_KEY": key}

    raw_dir.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s into %s", slug, raw_dir)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            KAGGLE_CLI,
            "datasets",
            "download",
            "-d",
            slug,
            "-p",
            str(raw_dir),
            "-f",
            target.name,
            "--unzip",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=child_env,
    )
    if result.returncode != 0:
        stderr = scrub_secrets(result.stderr or "", [username, key])
        raise RuntimeError(
            f"kaggle download failed (exit {result.returncode}): {stderr[-STDERR_TAIL_CHARS:]}"
        )

    # a single-file download stays zipped, --unzip does not apply to it
    for archive in raw_dir.glob("*.zip"):
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(raw_dir)
        archive.unlink()

    if not target.exists():
        present = sorted(file.name for file in raw_dir.iterdir())
        raise RuntimeError(f"expected {target.name} in {raw_dir}, found: {present}")

    checksum_path = raw_dir / get(settings, "dataset.checksum_filename")
    files = sorted(file for file in raw_dir.iterdir() if file.is_file() and file != checksum_path)
    landed = write_checksum_log(files, checksum_path)[target.name]
    log.info("downloaded %s, %s bytes, sha256 %s", target.name, landed["bytes"], landed["sha256"])
    return target
