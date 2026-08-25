from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from prometheus_observatory.object_store import ContentAddressedStore


def test_concurrent_content_addressed_writes_are_atomic(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path / "objects")
    payload = ("одинаковое содержимое 🚀" * 10_000).encode()

    def write_once():
        return store.put_stream(io.BytesIO(payload))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: write_once(), range(24)))
    assert len({result.sha256 for result in results}) == 1
    assert len({result.path for result in results}) == 1
    assert results[0].path.read_bytes() == payload
    assert not list(store.root.glob(".incoming-*"))
