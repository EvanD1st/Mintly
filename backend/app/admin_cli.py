"""One-time admin bootstrap. Read a strong password from stdin, never argv."""

import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User
from app.services.auth import hash_password


async def main() -> None:
    username = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "admin"
    if username != "admin":
        raise SystemExit("The first admin username must be admin.")
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        raise SystemExit("Send the initial password on stdin.")
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(User.id).where(User.role == "admin"))).first():
            raise SystemExit("An admin already exists; bootstrap refused.")
        db.add(User(username=username, password_hash=hash_password(password), role="admin",
                    is_active=True, must_change_password=True))
        await db.commit()
    print("Initial admin account created. Change its password at first sign-in.")


if __name__ == "__main__":
    asyncio.run(main())
