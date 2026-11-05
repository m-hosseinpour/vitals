#!/usr/bin/env python3
"""Set the dashboard password and store only its Argon2 hash in .env."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from argon2 import PasswordHasher

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
KEY = "VITALS_PASSWORD_HASH"
MIN_LENGTH = 12


def main() -> int:
    password = getpass.getpass("رمز عبور جدید: ")
    if len(password) < MIN_LENGTH:
        print(f"رمز عبور باید حداقل {MIN_LENGTH} کاراکتر باشد.", file=sys.stderr)
        return 1
    if password != getpass.getpass("تکرار رمز عبور: "):
        print("دو رمز واردشده یکسان نیستند.", file=sys.stderr)
        return 1

    digest = PasswordHasher().hash(password)
    lines = (
        ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    )
    updated = False
    for index, line in enumerate(lines):
        if line.startswith(f"{KEY}="):
            lines[index] = f"{KEY}={digest}"
            updated = True
            break
    if not updated:
        lines.append(f"{KEY}={digest}")

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ENV_FILE.with_name(f".{ENV_FILE.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, ENV_FILE)
    print(
        f"رمز عبور به‌روزرسانی شد. برای اعمال، سرویس را دوباره راه‌اندازی کنید: {ENV_FILE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
