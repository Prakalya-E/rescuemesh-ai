"""Audit local paths in a RescueMesh dataset manifest and fingerprint contents.

Paths are interpreted relative to --root. External references are reported but
never resolved. The input manifest is not modified unless output explicitly
points to the same file; that case requires an exact pre-existing backup path.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_external(value: str) -> bool:
    return bool(re.search(r"\b(external|https?://|api endpoint|configured in code)\b", value, re.I))


def resolve_one(raw: str, root: Path) -> dict[str, Any]:
    raw = raw.strip().strip('"')
    if not raw:
        return {"path": raw, "status": "empty_path"}
    if is_external(raw):
        return {"path": raw, "status": "external_reference"}
    # Reject drive/UNC paths and traversal before glob expansion.
    candidate = Path(raw)
    if candidate.is_absolute() or re.match(r"^[A-Za-z]:", raw) or raw.startswith(("\\\\", "//")):
        return {"path": raw, "status": "malformed_path", "error": "absolute paths are not allowed"}
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        return {"path": raw, "status": "malformed_path", "error": "parent traversal is not allowed"}
    has_glob = any(c in raw for c in "*?[")
    try:
        matches = sorted(root.glob(raw), key=lambda p: p.as_posix().casefold()) if has_glob else [root / candidate]
    except (OSError, ValueError) as exc:
        return {"path": raw, "status": "malformed_path", "error": f"glob error: {exc}"}
    found: list[Path] = []
    for path in matches:
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            continue
        except OSError as exc:
            return {"path": raw, "status": "inaccessible", "error": str(exc)}
        if not inside(resolved, root):
            return {"path": raw, "status": "malformed_path", "error": "resolved path escapes project root"}
        if resolved.is_file():
            found.append(resolved)
        elif resolved.is_dir():
            try:
                files = sorted((p.resolve(strict=True) for p in resolved.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix().casefold())
                if any(not inside(p, root) for p in files):
                    return {"path": raw, "status": "malformed_path", "error": "directory contains a file resolving outside project root"}
                if not files:
                    return {"path": raw, "status": "valid_empty_directory", "matched_paths": [], "file_count": 0}
                found.extend(files)
            except OSError as exc:
                return {"path": raw, "status": "inaccessible", "error": str(exc)}
    if not found:
        return {"path": raw, "status": "missing_path", "matched_paths": [], "file_count": 0}
    unique = sorted(set(found), key=lambda p: p.relative_to(root).as_posix().casefold())
    if not has_glob and len(matches) == 1 and matches[0].is_file() and len(unique) == 1:
        try:
            digest = sha256_file(unique[0])
        except OSError as exc:
            return {"path": raw, "status": "hash_error", "error": str(exc), "matched_paths": [str(unique[0].relative_to(root))]}
        rel = unique[0].relative_to(root).as_posix()
        return {"path": raw, "status": "hashed_file", "sha256": digest, "file_count": 1, "matched_paths": [rel], "file_hashes": [{"path": rel, "sha256": digest}]}
    items = []
    try:
        for p in unique:
            items.append((p.relative_to(root).as_posix(), sha256_file(p)))
    except OSError as exc:
        return {"path": raw, "status": "hash_error", "error": str(exc), "file_count": len(items)}
    h = hashlib.sha256()
    for rel, digest in items:
        h.update(rel.encode("utf-8")); h.update(b"\0")
        h.update(digest.encode("ascii")); h.update(b"\n")
    status = "hashed_collection" if len(items) > 1 or not has_glob else "hashed_file_collection"
    return {"path": raw, "status": status, "sha256": h.hexdigest().upper(), "file_count": len(items), "matched_paths": [r for r, _ in items], "file_hashes": [{"path": rel, "sha256": digest} for rel, digest in items]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="project root")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True, help="backup path for input manifest")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source = args.manifest.resolve(strict=True)
    output = args.output_manifest.resolve() if args.output_manifest.exists() else args.output_manifest.absolute()
    report = args.json_report.resolve() if args.json_report.exists() else args.json_report.absolute()
    summary_path = args.summary.resolve() if args.summary.exists() else args.summary.absolute()
    backup = args.backup.resolve() if args.backup.exists() else args.backup.absolute()
    for target in (output, report, summary_path, backup):
        if not inside(target, root):
            raise SystemExit(f"Refusing output outside project root: {target}")
    if output.exists() and output != source:
        raise SystemExit(f"Refusing to overwrite existing output manifest: {output}")
    if report.exists() or summary_path.exists():
        raise SystemExit("Refusing to overwrite an existing JSON report or summary")
    if backup.exists():
        if backup.read_bytes() != source.read_bytes():
            raise SystemExit(f"Backup exists and differs from input: {backup}")
    else:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "local_path" not in reader.fieldnames:
            raise SystemExit("Manifest requires a local_path column")
        original_fields = list(reader.fieldnames)
        rows = list(reader)
    extra_fields = ["checksum", "checksum_file_count", "path_audit_status", "path_audit_details"]
    fields = original_fields + [f for f in extra_fields if f not in original_fields]
    inventory: list[dict[str, Any]] = []
    path_to_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    path_rows: list[list[dict[str, Any]]] = []
    status_counts: Counter[str] = Counter()
    for i, row in enumerate(rows, 1):
        raw = row.get("local_path", "") or ""
        components = raw.split(";")
        details = [resolve_one(component, root) for component in components]
        for component_index, d in enumerate(details, 1):
            status_counts[d["status"]] += 1
            for p in d.get("matched_paths", []):
                path_to_rows[p.casefold()].append({"row": i, "component": component_index, "dataset_name": row.get("dataset_name", "")})
        valid = [d for d in details if d["status"].startswith("hashed_")]
        counts = [d.get("file_count", 0) for d in details]
        if len(details) == 1 and len(valid) == 1:
            row["checksum"] = valid[0]["sha256"]
        elif valid:
            h = hashlib.sha256()
            for d in details:
                h.update(d["path"].encode("utf-8")); h.update(b"\0")
                h.update(d.get("sha256", d["status"]).encode("utf-8")); h.update(b"\n")
            row["checksum"] = h.hexdigest().upper()
        else:
            row["checksum"] = "Unknown / no local checksum"
        row["checksum_file_count"] = str(sum(counts))
        statuses = [d["status"] for d in details]
        row["path_audit_status"] = ";".join(statuses)
        row["path_audit_details"] = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
        inventory.append({"manifest_row": i, "dataset_name": row.get("dataset_name", ""), "local_path": raw, "components": details})
        path_rows.append(details)
    duplicates = {p: refs for p, refs in path_to_rows.items() if len(refs) > 1}
    physical_file_references = sum(len(d.get("matched_paths", [])) for row in inventory for d in row["components"])
    overlaps = []
    for left in range(len(path_rows)):
        left_files = {p.casefold() for d in path_rows[left] for p in d.get("matched_paths", [])}
        for right in range(left + 1, len(path_rows)):
            common = sorted(left_files & {p.casefold() for d in path_rows[right] for p in d.get("matched_paths", [])})
            if common:
                overlaps.append({"manifest_rows": [left + 1, right + 1], "shared_file_count": len(common), "sample_paths": common[:10]})
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.output_manifest.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    # Read back and independently recompute representative first and last local files.
    with args.output_manifest.open("r", encoding="utf-8-sig", newline="") as stream:
        reread = list(csv.DictReader(stream))
    checks = []
    candidates = [(row, comp) for row in inventory for comp in row["components"] if comp.get("matched_paths")]
    collection_candidates = [(row, comp) for row, comp in candidates if comp["status"] in {"hashed_collection", "hashed_file_collection"}]
    representative = candidates[:1] + (collection_candidates[:1] if collection_candidates else []) + (candidates[-1:] if len(candidates) > 1 else [])
    seen_representatives = set()
    representative = [(row, comp) for row, comp in representative if (row["manifest_row"], comp["path"]) not in seen_representatives and not seen_representatives.add((row["manifest_row"], comp["path"]))]
    for row_info, item in representative:
        independent = resolve_one(item["path"], root)
        written_checksum = reread[row_info["manifest_row"] - 1].get("checksum")
        checks.append({"path": item["path"], "manifest_row": row_info["manifest_row"], "stored_component_sha256": item.get("sha256"), "independent_sha256": independent.get("sha256"), "written_manifest_checksum": written_checksum, "verified": independent.get("sha256") == item.get("sha256") and independent.get("status") == item.get("status") and written_checksum == rows[row_info["manifest_row"] - 1].get("checksum")})
    payload = {"generated_utc": datetime.now(timezone.utc).isoformat(), "root": str(root), "input_manifest": str(source), "output_manifest": str(args.output_manifest), "rows": len(rows), "status_counts": dict(status_counts), "physical_file_references": physical_file_references, "unique_physical_files": len(path_to_rows), "duplicate_paths_across_rows": duplicates, "overlapping_collections": overlaps, "verification": {"rows_written_and_read": len(reread) == len(rows), "representative_rechecks": checks}, "datasets": inventory}
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    missing_or_issue = sum(v for k, v in status_counts.items() if k not in {"hashed_file", "hashed_collection", "hashed_file_collection", "valid_empty_directory", "external_reference"})
    lines = ["# Dataset manifest audit summary", "", f"- Manifest rows: {len(rows)}", f"- Path components: {sum(status_counts.values())}", f"- Component statuses: {json.dumps(dict(status_counts), sort_keys=True)}", f"- Physical file references: {physical_file_references}", f"- Unique physical files: {len(path_to_rows)}", f"- Duplicate paths across manifest rows: {len(duplicates)}", f"- Overlapping row pairs: {len(overlaps)}", f"- Unresolved/malformed/inaccessible/hash-error component count: {missing_or_issue}", f"- Output manifest readback rows: {len(reread)}", f"- Backup: `{backup}`", "", "Collection fingerprints hash sorted root-relative paths and each file SHA-256. External references are not hashed."]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if missing_or_issue else 0


if __name__ == "__main__":
    raise SystemExit(main())
