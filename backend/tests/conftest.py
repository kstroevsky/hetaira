from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

os.environ["PROMETHEUS_SEED_DEMO"] = "false"

from prometheus_observatory import models  # noqa: E402,F401
from prometheus_observatory.database import Base, create_configured_engine  # noqa: E402


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    engine = create_configured_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
