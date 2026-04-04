from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from wdsync.core.models import PathFingerprint
from wdsync.core.runner import CommandRunner


def read_repo_path_fingerprints(
    command: Sequence[str],
    repo_root: Path,
    runner: CommandRunner,
    paths: tuple[str, ...],
) -> tuple[PathFingerprint, ...]:
    unique_paths = tuple(dict.fromkeys(paths))
    fingerprints: list[PathFingerprint] = []

    for path in unique_paths:
        full_path = repo_root / Path(path)
        if not full_path.exists():
            fingerprints.append(PathFingerprint(path=path, object_id=None))
            continue
        result = runner.run([*command, "hash-object", "--path", path, str(full_path)])
        fingerprints.append(
            PathFingerprint(
                path=path,
                object_id=result.stdout_text().strip() or None,
            )
        )

    return tuple(fingerprints)
