from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    size_bytes: int
    path: Path


class ContentAddressedStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_stream(self, stream: BinaryIO) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(
            dir=self.root, prefix=".incoming-", delete=False
        ) as output:
            temporary = Path(output.name)
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        sha256 = digest.hexdigest()
        destination = self.root / sha256[:2] / sha256[2:4] / sha256
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        return StoredObject(sha256=sha256, size_bytes=size, path=destination)
