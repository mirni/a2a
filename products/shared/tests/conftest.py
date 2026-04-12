"""Conftest for the shared product's own tests.

This conftest exposes the ``tmp_db`` fixture from ``_conftest_base``.

Importantly, the shared product itself does **not** need the
``register_shared_src`` virtual-package hack: the ``src`` module it
imports at test time already *is* ``products/shared/src``, so
registering a second ``shared_src`` alias would create two distinct
copies of every module (different class identities) and break
``pytest.raises(X)`` matches against exceptions raised from the
aliased copy. Downstream products that do need cross-product imports
(``billing``, ``payments``, …) call ``register_shared_src`` from
their own conftest — see ``_conftest_base.register_shared_src`` for
the contract.
"""

from __future__ import annotations

import os
import sys

# _conftest_base lives next to this file; add the directory to sys.path
# so pytest (which may be invoked from anywhere) can import it.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _conftest_base import tmp_db  # noqa: F401, E402
