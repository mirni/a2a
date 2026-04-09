"""Z3 Verifier Lambda Connector."""

import os as _os

# Extend this package's path to include the shared 'src' directory
_shared_src = _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "shared", "src")
_shared_src = _os.path.normpath(_shared_src)
if _os.path.isdir(_shared_src) and _shared_src not in __path__:
    __path__.append(_shared_src)
