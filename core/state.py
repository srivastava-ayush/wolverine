"""Atomic state snapshots; the directory must be private to this service."""
import json
import os
import re
import tempfile
from pathlib import Path

from core.models import Run, now


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def directory(self, run_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("Invalid run ID")
        return self.root / run_id

    def save(self, run: Run):
        directory = self.directory(run.id)
        directory.mkdir(mode=0o700, exist_ok=True)
        run.updated_at = now()
        fd, path = tempfile.mkstemp(dir=directory, prefix=".state-")
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(run.as_dict(), file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(path, directory / "run.json")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def load(self, run_id: str) -> Run:
        with (self.directory(run_id) / "run.json").open() as file:
            return Run.from_dict(json.load(file))
