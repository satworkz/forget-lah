"""Keep Bridge version receipts within the existing message storage contract."""

import hashlib


def compact_bridge_source_version(version: str) -> str:
    if version.startswith("bridge:") and len(version) > 40:
        return "bridge:" + hashlib.sha256(version.encode("utf-8")).hexdigest()[:33]
    return version
