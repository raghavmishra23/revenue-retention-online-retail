import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingest import download
from src.ingest.download import file_checksum, scrub_secrets, write_checksum_log

FAKE_USER = "fakeuser"
FAKE_KEY = "fakekey123"


def freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the timestamp so two writes of the checksum log compare byte for byte."""
    fixed = datetime(2024, 1, 1, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return fixed

    monkeypatch.setattr(download, "datetime", FixedDatetime)


@pytest.fixture
def raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(download, "resolve_path", lambda key: tmp_path)
    monkeypatch.setattr(
        download, "require_env", lambda name: FAKE_USER if name.endswith("USERNAME") else FAKE_KEY
    )
    return tmp_path


def test_file_checksum_matches_known_digest(tmp_path: Path) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"retail")
    assert file_checksum(sample) == hashlib.sha256(b"retail").hexdigest()


def test_checksum_log_is_valid_and_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"retail")
    log_path = tmp_path / "checksums.json"
    freeze_clock(monkeypatch)

    write_checksum_log([sample], log_path)
    first = log_path.read_bytes()
    write_checksum_log([sample], log_path)

    entry = json.loads(first)["sample.bin"]
    assert set(entry) == {"sha256", "bytes", "downloaded_at"}
    assert entry["bytes"] == 6
    assert first.endswith(b"\n")
    assert log_path.read_bytes() == first


def test_scrub_secrets_masks_every_value() -> None:
    text = f"401 for {FAKE_USER} using {FAKE_KEY}"
    cleaned = scrub_secrets(text, [FAKE_USER, FAKE_KEY])
    assert FAKE_USER not in cleaned
    assert FAKE_KEY not in cleaned
    assert "***" in cleaned


def test_download_skips_when_workbook_exists(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workbook = raw_dir / download.get(download.load_settings(), "dataset.raw_filename")
    workbook.write_bytes(b"x")

    def fail(*args: object, **kwargs: object) -> None:
        pytest.fail("subprocess.run should not be called")

    monkeypatch.setattr(subprocess, "run", fail)
    assert download.download_dataset() == workbook


def test_failed_download_raises_without_leaking_credentials(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", f"403 forbidden for {FAKE_KEY}")

    monkeypatch.setattr(subprocess, "run", failing_run)
    with pytest.raises(RuntimeError) as error:
        download.download_dataset()
    assert FAKE_KEY not in str(error.value)
    assert "403" in str(error.value)


def test_download_extracts_single_file_zip_and_logs_checksums(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workbook_name = download.get(download.load_settings(), "dataset.raw_filename")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        with zipfile.ZipFile(raw_dir / f"{workbook_name}.zip", "w") as bundle:
            bundle.writestr(workbook_name, "workbook bytes")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    workbook = download.download_dataset()

    assert workbook.exists()
    assert list(raw_dir.glob("*.zip")) == []
    entry = json.loads((raw_dir / "checksums.json").read_text(encoding="utf-8"))[workbook_name]
    assert entry["bytes"] == len("workbook bytes")


def test_download_reports_what_landed_when_the_workbook_is_missing(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        (raw_dir / "something_else.csv").write_text("nope", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="something_else.csv"):
        download.download_dataset()
