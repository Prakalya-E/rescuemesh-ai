from pathlib import Path
import csv
import json
import sys

import pytest

from scripts.audit_dataset_manifest import main, resolve_one, sha256_file


def test_hashes_individual_file(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    item = root / "data.csv"
    item.write_bytes(b"a,b\n1,2\n")

    result = resolve_one("data.csv", root.resolve())

    assert result["status"] == "hashed_file"
    assert result["sha256"] == sha256_file(item)
    assert result["file_count"] == 1


def test_hashes_wildcard_collection_deterministically(tmp_path: Path):
    root = tmp_path / "project"
    folder = root / "data"
    folder.mkdir(parents=True)
    (folder / "b.nc").write_bytes(b"b")
    (folder / "a.nc").write_bytes(b"a")

    first = resolve_one("data/*.nc", root.resolve())
    second = resolve_one("data/*.nc", root.resolve())

    assert first == second
    assert first["status"] == "hashed_collection"
    assert first["file_count"] == 2
    assert first["matched_paths"] == ["data/a.nc", "data/b.nc"]


def test_hashes_directory_recursively(tmp_path: Path):
    root = tmp_path / "project"
    folder = root / "tiles" / "nested"
    folder.mkdir(parents=True)
    (folder / "tile.bin").write_bytes(b"tile")

    result = resolve_one("tiles", root.resolve())

    assert result["status"] == "hashed_collection"
    assert result["file_count"] == 1
    assert result["matched_paths"] == ["tiles/nested/tile.bin"]


def test_distinguishes_empty_missing_external_and_malformed(tmp_path: Path):
    root = tmp_path / "project"
    (root / "empty").mkdir(parents=True)

    assert resolve_one("empty", root.resolve())["status"] == "valid_empty_directory"
    assert resolve_one("missing.csv", root.resolve())["status"] == "missing_path"
    assert resolve_one("External source configured in code", root.resolve())["status"] == "external_reference"
    assert resolve_one("../outside.csv", root.resolve())["status"] == "malformed_path"
    assert resolve_one("C:/outside.csv", root.resolve())["status"] == "malformed_path"


def test_empty_manifest_path_is_reported(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    assert resolve_one("", root.resolve())["status"] == "empty_path"


def test_manifest_cli_backs_up_hashes_and_reads_back(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    (root / "data" / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    source = root / "manifest.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["dataset_name", "local_path", "license"])
        writer.writeheader()
        writer.writerow({"dataset_name": "sample", "local_path": "data/*.csv", "license": "unknown"})
        writer.writerow({"dataset_name": "remote", "local_path": "External source configured in code", "license": "unknown"})
    output = root / "audited.csv"
    report = root / "audit.json"
    summary = root / "summary.md"
    backup = root / "manifest.backup.csv"
    monkeypatch.setattr(sys, "argv", ["audit_dataset_manifest.py", "--root", str(root), "--manifest", str(source), "--output-manifest", str(output), "--json-report", str(report), "--summary", str(summary), "--backup", str(backup)])

    assert main() == 0
    assert backup.read_bytes() == source.read_bytes()
    with output.open(encoding="utf-8-sig", newline="") as stream:
        result = list(csv.DictReader(stream))
    audit = json.loads(report.read_text(encoding="utf-8"))
    assert len(result) == 2
    assert result[0]["checksum_file_count"] == "1"
    assert result[0]["license"] == "unknown"
    assert result[1]["path_audit_status"] == "external_reference"
    assert audit["verification"]["rows_written_and_read"] is True
    assert audit["physical_file_references"] == 1
    assert audit["unique_physical_files"] == 1
    assert all(item["verified"] for item in audit["verification"]["representative_rechecks"])
    assert audit["datasets"][0]["components"][0]["file_hashes"] == [
        {"path": "data/sample.csv", "sha256": sha256_file(root / "data" / "sample.csv")}
    ]


def test_manifest_cli_refuses_to_overwrite_existing_output(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "manifest.csv"
    source.write_text("dataset_name,local_path\n,missing.csv\n", encoding="utf-8")
    output = root / "audited.csv"
    output.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["audit_dataset_manifest.py", "--root", str(root), "--manifest", str(source), "--output-manifest", str(output), "--json-report", str(root / "audit.json"), "--summary", str(root / "summary.md"), "--backup", str(root / "backup.csv")])

    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        main()
    assert output.read_text(encoding="utf-8") == "preserve"
