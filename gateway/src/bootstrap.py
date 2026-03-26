"""Bootstrap cross-product imports.

All products use `src/` as their package root, which causes namespace collisions.
This module loads each product's modules under unique prefixes.

After calling bootstrap(), modules are available as:

  billing_src.tracker, billing_src.wallet, billing_src.storage, ...
  paywall_src.keys, paywall_src.tiers, paywall_src.storage, ...
  payments_src.engine, payments_src.storage, payments_src.models, ...
  marketplace_src.marketplace, marketplace_src.models, marketplace_src.storage
  trust_src.api, trust_src.scorer, trust_src.storage, trust_src.models
"""

from __future__ import annotations

import importlib
import os
import sys
import types

_PRODUCTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "products")
)

_bootstrapped = False

# Stash billing's src modules so payments can find them as `src.*`
_billing_src_modules: dict[str, types.ModuleType] = {}


def _clear_src_modules() -> None:
    """Remove 'src' and 'src.*' entries from sys.modules."""
    for key in list(sys.modules.keys()):
        if key == "src" or key.startswith("src."):
            del sys.modules[key]


def _load_product_simple(product_name: str, prefix: str) -> None:
    """Load a product that uses only relative imports (from .xxx)."""
    product_root = os.path.join(_PRODUCTS_DIR, product_name)
    src_dir = os.path.join(product_root, "src")

    _clear_src_modules()
    sys.path.insert(0, product_root)

    try:
        importlib.import_module("src")

        for fname in sorted(os.listdir(src_dir)):
            if fname.endswith(".py") and fname != "__init__.py":
                mod_name = fname[:-3]
                try:
                    importlib.import_module(f"src.{mod_name}")
                except Exception:
                    pass

        # Re-register under prefixed names
        for key in list(sys.modules.keys()):
            if key == "src" or key.startswith("src."):
                mod = sys.modules.pop(key)
                prefixed = key.replace("src", f"{prefix}_src", 1)
                sys.modules[prefixed] = mod
    finally:
        if product_root in sys.path:
            sys.path.remove(product_root)


def _load_billing() -> None:
    """Load billing and stash its src modules for payments to use."""
    _load_product_simple("billing", "billing")

    # Stash copies so we can restore them for payments
    for key, mod in sys.modules.items():
        if key.startswith("billing_src"):
            # Map billing_src.X → src.X
            src_key = key.replace("billing_src", "src", 1)
            _billing_src_modules[src_key] = mod


def _load_payments() -> None:
    """Load payments — needs both 'payments.*' virtual pkg and billing's 'src.*'."""
    product_root = os.path.join(_PRODUCTS_DIR, "payments")
    src_dir = os.path.join(product_root, "src")

    _clear_src_modules()

    # 1. Restore billing's src.* modules so `from src.wallet import ...` works
    for key, mod in _billing_src_modules.items():
        sys.modules[key] = mod

    # 2. Register 'payments' virtual package pointing to payments/src/
    if "payments" not in sys.modules:
        pkg = types.ModuleType("payments")
        pkg.__path__ = [src_dir]
        pkg.__package__ = "payments"
        sys.modules["payments"] = pkg

    # 3. Import payment submodules via the virtual package
    for fname in sorted(os.listdir(src_dir)):
        if fname.endswith(".py") and fname != "__init__.py":
            mod_name = fname[:-3]
            try:
                importlib.import_module(f"payments.{mod_name}")
            except Exception:
                pass

    # 4. Register under payments_src.* prefix too
    for key in list(sys.modules.keys()):
        if key.startswith("payments."):
            mod = sys.modules[key]
            prefixed = key.replace("payments.", "payments_src.", 1)
            sys.modules[prefixed] = mod

    # Also register the package itself
    if "payments" in sys.modules:
        sys.modules["payments_src"] = sys.modules["payments"]

    # 5. Clean up billing's src.* (leave billing_src.* intact)
    _clear_src_modules()


def bootstrap() -> None:
    """Load all product modules under unique prefixes."""
    global _bootstrapped
    if _bootstrapped:
        return

    _load_billing()
    _load_product_simple("paywall", "paywall")
    _load_payments()
    _load_product_simple("marketplace", "marketplace")
    _load_product_simple("trust", "trust")

    _bootstrapped = True


# Run on import
bootstrap()
