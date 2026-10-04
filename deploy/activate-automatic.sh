#!/usr/bin/env bash
set -euo pipefail
# Explicit operator action after the account owner authorizes production activation.
# Does not create or arm tasks. Subsequent deployments preserve this recorded choice.
APP_DIR="${APP_DIR:-$HOME/Mintly}"
RELEASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
test -f "$APP_DIR/shared/custody.env"
sudo -n docker exec -i mintly-backend-1 python - <<'PY'
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import httpx
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AutomaticGrant, MintTask
from app.services.mint_plans import aware
async def check():
    async with AsyncSessionLocal() as db:
        pending = (await db.execute(select(MintTask.id).where(
            MintTask.execution_mode == 'custodial_v1',
            MintTask.status.in_(['armed', 'preparing', 'prepared', 'submitted', 'uncertain'])))).scalars().all()
        if pending and not settings.ENABLE_CUSTODIAL_AUTOMATIC:
            raise RuntimeError('Review existing pending authorizations before first activation.')
        policies = (await db.execute(select(AutomaticGrant).where(AutomaticGrant.status == 'enabled'))).scalars().all()
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            headers = {'Authorization': 'Bearer ' + Path(settings.AUTOMATIC_SIGNER_TOKEN_FILE).read_text().strip()}
            response = await client.get(settings.AUTOMATIC_SIGNER_URL + '/readyz', headers=headers)
            response.raise_for_status()
            assert response.json()['chain_id'] == settings.AUTOMATIC_CHAIN_ID
            ready = 0
            for policy in policies:
                if aware(policy.expires_at) <= datetime.now(timezone.utc):
                    continue
                response = await client.get(settings.AUTOMATIC_SIGNER_URL + f'/policies/{policy.id}/ready', headers=headers)
                response.raise_for_status()
                ready += 1
            print(f'Signer verified; {ready} valid policies; {len(pending)} pending tasks. No task armed.')
asyncio.run(check())
PY
python3 - "$APP_DIR/shared/custody.env" <<'PY'
import os, sys
from pathlib import Path
path = Path(sys.argv[1])
updates = {'CUSTODY_TASK_ARMING': 'true', 'CUSTODY_AUTOMATIC_WORKER': 'true'}
lines = [line for line in path.read_text().splitlines() if line.split('=', 1)[0] not in updates]
lines += [f'{key}={value}' for key, value in updates.items()]
temporary = path.with_suffix('.activation.tmp')
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write('\n'.join(lines) + '\n')
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
os.chmod(path, 0o600)
PY
bash "$RELEASE_DIR/deploy/deploy-ubuntu.sh"
