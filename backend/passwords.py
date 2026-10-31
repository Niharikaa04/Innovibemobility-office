"""Verify-only password checking. Detects the stored scheme; never re-hashes or writes. Unknown schemes fail closed."""
def detect_scheme(stored: str) -> str:
    s = (stored or "").strip()
    if s.startswith(("$2a$", "$2b$", "$2y$")): return "bcrypt"
    if s.startswith("$argon2"): return "argon2"
    if s.startswith(("pbkdf2:", "scrypt:")): return "werkzeug"
    if s.startswith("$pbkdf2-"): return "passlib-pbkdf2"
    return "unknown"

def verify(plain: str, stored: str):
    scheme, s = detect_scheme(stored), (stored or "").strip()
    try:
        if scheme == "bcrypt":
            import bcrypt; return bcrypt.checkpw(plain.encode()[:72], s.encode()), scheme
        if scheme == "argon2":
            from argon2 import PasswordHasher; return PasswordHasher().verify(s, plain), scheme
        if scheme == "werkzeug":
            from werkzeug.security import check_password_hash; return check_password_hash(s, plain), scheme
        if scheme == "passlib-pbkdf2":
            from passlib.hash import pbkdf2_sha256; return pbkdf2_sha256.verify(plain, s), scheme
    except Exception:
        return False, scheme
    return False, scheme
