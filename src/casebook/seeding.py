"""Every random stream derives from the seed and a named subject; nothing reads the clock.

The version is left out, so a release changes only what its errata entry names (the owner's
decision of 16 November 2026).
"""

import hashlib
import random


def derive_rng(*parts: object) -> random.Random:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
