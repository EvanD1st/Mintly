"""Manual recovery CLI. Run only inside the isolated signer after owner consent."""
import argparse
import asyncio
from datetime import datetime
import json
from app.database import AsyncSessionLocal
from app.services.custody_recovery import recover_task


async def main(args):
    async with AsyncSessionLocal() as db:
        result = await recover_task(db, args.task, args.owner,
            datetime.fromisoformat(args.expires_at.replace('Z', '+00:00')), args.authorization_reference)
        print(json.dumps(result))  # public identifiers only; never raw signatures or keys


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--expires-at', required=True)
    parser.add_argument('--authorization-reference', required=True)
    parser.add_argument('--confirm-exact-recovery', action='store_true', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except Exception as error:
        # RPC exceptions can contain signed payloads. Do not emit tracebacks/payloads.
        print(json.dumps({'status': 'rejected', 'reason': str(error) if isinstance(error, ValueError)
                         else type(error).__name__}))
        raise SystemExit(1)
