"""Every random stream derives from the seed, the version and a named subject; nothing reads the clock."""

import hashlib
import random


def derive_rng(*parts: object) -> random.Random:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
