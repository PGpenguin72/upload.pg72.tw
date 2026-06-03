import secrets

# Removed: I, O (letter), 0, 1 (digit) — visually ambiguous
SAFE_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 16


def generate_code() -> str:
    return "".join(secrets.choice(SAFE_CHARSET) for _ in range(CODE_LENGTH))
