"""Import every module that defines tables, so Base.metadata is complete.

Alembic (env.py), app.migrate and the application import this one module; a new
module with tables is added here and nowhere else.
"""
from app.integration import models as _integration  # noqa: F401
from app.platform import models as _platform  # noqa: F401
from app.modules.strategy import models as _strategy  # noqa: F401
