"""Create a local Twikit session for Mintly without storing an X password.

Run this yourself in a terminal. Do not paste the password or resulting JSON into chat.
"""

import argparse
import asyncio
import getpass
import os
from pathlib import Path
import tempfile

from twikit import Client


SESSION_FILE = Path.home() / ".ssh" / "mintly-x-cookies.json"


async def login_and_verify(username: str, second_id: str | None, password: str) -> Client:
    client = Client("en-US")
    await client.login(auth_info_1=username, auth_info_2=second_id,
                       password=password, enable_ui_metrics=True)
    target = await client.get_user_by_screen_name("lakzonevn")
    if str(getattr(target, "screen_name", "")).lower() != "lakzonevn":
        raise RuntimeError("X returned a different account for @lakzonevn.")
    await client.get_user_tweets(target.id, "Tweets", count=1)
    return client


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a verified local X session for Mintly's Twikit worker")
    parser.add_argument("--replace", action="store_true", help="Replace an expired local session only after a successful login")
    args = parser.parse_args()
    if SESSION_FILE.exists() and not args.replace:
        print(f"A session already exists at {SESSION_FILE}. Use --replace only if it has expired.")
        return 1

    print("This signs your X account into Twikit once and checks read access to @lakzonevn.")
    print("Your password is hidden and never written to the session file or Mintly repository.")
    username = input("Your X username or email: ").strip()
    second_id = input("Other login identifier (email or username; Enter to skip): ").strip() or None
    password = getpass.getpass("X password (hidden): ")
    if not username or not password:
        print("A username/email and password are required.")
        return 1

    try:
        client = asyncio.run(login_and_verify(username, second_id, password))
    except Exception as error:
        print(f"X login or read check failed ({type(error).__name__}). No session was saved.")
        return 1
    finally:
        password = None

    SESSION_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old_mask = os.umask(0o077)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".mintly-x-", suffix=".json", dir=SESSION_FILE.parent)
        os.close(fd)
        temporary = Path(name)
        client.save_cookies(str(temporary))
        if temporary.stat().st_size == 0:
            raise RuntimeError("Twikit saved an empty session.")
        temporary.chmod(0o600)
        os.replace(temporary, SESSION_FILE)
        SESSION_FILE.chmod(0o600)
    except Exception as error:
        print(f"Could not save the X session ({type(error).__name__}).")
        return 1
    finally:
        os.umask(old_mask)
        if temporary and temporary.exists():
            temporary.unlink()

    print(f"Verified X session saved at {SESSION_FILE}.")
    print("Do not paste or attach that file in chat. Tell Codex only that the file is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
