from __future__ import annotations

import hashlib
import shutil
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
        temporary = self.root / ".incoming"
        digest = hashlib.sha256()
        size = 0
        with temporary.open("wb") as output:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
        sha256 = digest.hexdigest()
        destination = self.root / sha256[:2] / sha256[2:4] / sha256
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temporary.unlink()
        else:
            shutil.move(str(temporary), destination)
        return StoredObject(sha256=sha256, size_bytes=size, path=destination)
