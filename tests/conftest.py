import sys
from pathlib import Path

# Ensure workspace root has precedence in sys.path over tests/ so 'import server'
# resolves to the server package rather than the tests/server directory.
_root_dir = str(Path(__file__).resolve().parent.parent)
if sys.path and sys.path[0] != _root_dir:
    if _root_dir in sys.path:
        sys.path.remove(_root_dir)
    sys.path.insert(0, _root_dir)

from tests.fixtures import client, isolated_env, manager

__all__ = ["client", "isolated_env", "manager"]

