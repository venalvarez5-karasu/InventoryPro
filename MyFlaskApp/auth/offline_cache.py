
import hashlib
import json
import os
from pathlib import Path
from functools import wraps

from flask import current_app


CACHE_DIR = Path(__file__).resolve().parent / "location_cache"


def install_offline_address_cache():
    """
    Add persistent local caching to the existing
    Philippine location API helper.

    Does not replace existing address validation.
    """

    import importlib

    auth_module = importlib.import_module(
        "MyFlaskApp.auth.auth_bp"
    )

    original_fetch = auth_module.fetch_psgc

    if getattr(original_fetch, "_offline_cache_installed", False):
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @wraps(original_fetch)
    def cached_fetch(path):
        key = hashlib.sha256(
            path.encode("utf-8")
        ).hexdigest()

        cache_file = CACHE_DIR / f"{key}.json"

        try:
            items = original_fetch(path)

            if isinstance(items, list):
                temporary = cache_file.with_suffix(".tmp")

                try:
                    temporary.write_text(
                        json.dumps(items, ensure_ascii=False),
                        encoding="utf-8"
                    )

                    os.replace(temporary, cache_file)

                except OSError:
                    current_app.logger.warning(
                        "Could not save location cache"
                    )

            return items

        except Exception:
            if cache_file.is_file():
                try:
                    saved = json.loads(
                        cache_file.read_text(encoding="utf-8")
                    )

                    if isinstance(saved, list):
                        current_app.logger.warning(
                            "Using cached Philippine location data"
                        )
                        return saved

                except (OSError, ValueError):
                    current_app.logger.warning(
                        "Saved location cache is invalid"
                    )

            raise

    cached_fetch._offline_cache_installed = True

    auth_module.fetch_psgc = cached_fetch
