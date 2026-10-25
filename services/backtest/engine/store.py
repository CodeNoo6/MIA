"""File-backed run storage with verifiable hashes (FR-09, FR-10).

Everything lives under one directory so a Railway volume mounted there persists it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        (root / "runs").mkdir(parents=True, exist_ok=True)
        (root / "families").mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        path = (self.root / "runs" / run_id).resolve()
        if path.parent != (self.root / "runs").resolve():
            raise KeyError(run_id)
        return path

    def exists(self, run_id: str) -> bool:
        return self.run_dir(run_id).joinpath("result.json").is_file()

    def family_runs(self, family_id: str) -> list[str]:
        path = self.root / "families" / f"{family_id}.json"
        return json.loads(path.read_text()) if path.is_file() else []

    def _append_family(self, family_id: str, run_id: str) -> None:
        runs = self.family_runs(family_id) + [run_id]
        (self.root / "families" / f"{family_id}.json").write_text(json.dumps(runs))

    def next_combinations(self, family_id: str | None, declared_variants: int) -> int:
        """Every rerun in a family adds one to the N the deflated Sharpe corrects for."""
        reruns = len(self.family_runs(family_id)) if family_id else 0
        return declared_variants + reruns

    def save(
        self,
        result: dict,
        inputs: dict[str, bytes],
        family_id: str | None,
        parent_id: str | None,
    ) -> dict:
        run_id = uuid.uuid4().hex
        family = family_id or run_id
        directory = self.run_dir(run_id)
        directory.mkdir(parents=True)
        for name, data in inputs.items():
            directory.joinpath(name).write_bytes(data)
        record = {
            **result,
            "run_id": run_id,
            "family_id": family,
            "parent_id": parent_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_hashes": {name: digest(data) for name, data in inputs.items()},
        }
        record["report_hash"] = digest(canonical(record))
        directory.joinpath("result.json").write_bytes(canonical(record))
        self._append_family(family, run_id)
        return record

    def load(self, run_id: str) -> dict:
        path = self.run_dir(run_id) / "result.json"
        if not path.is_file():
            raise KeyError(run_id)
        return json.loads(path.read_text())

    def load_input(self, run_id: str, name: str) -> bytes | None:
        path = self.run_dir(run_id) / name
        return path.read_bytes() if path.is_file() else None

    def verify(self, run_id: str) -> dict:
        record = self.load(run_id)
        stored = record.pop("report_hash")
        recomputed = digest(canonical(record))
        return {"run_id": run_id, "report_hash": stored, "valid": stored == recomputed}
