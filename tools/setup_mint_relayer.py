"""Create/show an operator-only gas relayer. Never import user wallet keys."""
import argparse
import os
from pathlib import Path
from eth_account import Account

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--key-file',required=True)
parser.add_argument('--create',action='store_true')
args=parser.parse_args()
path=Path(args.key_file).expanduser()
if not path.exists():
    if not args.create: parser.error('Relayer not configured. Use --create to generate an operator gas wallet.')
    path.parent.mkdir(parents=True,exist_ok=True)
    account=Account.create()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream: stream.write(account.key.hex())
    os.chmod(path,0o600)
account=Account.from_key(path.read_text().strip())
print('Operator gas relayer address:',account.address)
print('No user wallet key was imported. Fund only operating gas on supported networks.')
