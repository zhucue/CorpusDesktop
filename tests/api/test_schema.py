from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from services.api.db import engine
from services.api.models import Base


def test_migration_matches_models():
    with engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
