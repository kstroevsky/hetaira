from __future__ import annotations

import hashlib
import os
import tarfile
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

    def put_directory(self, directory: Path) -> StoredObject:
        if not directory.is_dir():
            raise ValueError("directory artifact source must be a directory")
        with tempfile.NamedTemporaryFile(
            dir=self.root, prefix=".directory-", suffix=".tar", delete=False
        ) as temporary_handle:
            temporary = Path(temporary_handle.name)
        try:
            with tarfile.open(temporary, mode="w") as archive:
                for source in sorted(path for path in directory.rglob("*") if path.is_file()):
                    if source.is_symlink():
                        continue
                    relative = source.relative_to(directory)

                    def deterministic(info: tarfile.TarInfo) -> tarfile.TarInfo:
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = 0
                        return info

                    archive.add(
                        source,
                        arcname=str(relative),
                        recursive=False,
                        filter=deterministic,
                    )
            with temporary.open("rb") as stream:
                return self.put_stream(stream)
        finally:
            if temporary.exists():
                temporary.unlink()
