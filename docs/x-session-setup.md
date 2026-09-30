# Set up the shared X reader

Mintly needs **one** authenticated X session on its Ubuntu worker to read
@lakzonevn. Your Mintly users do not need X accounts. The worker only calls
Twikit's account lookup and timeline read methods; it does not post or interact
with your X account. The resulting cookie file is an account session and must be
kept as carefully as a password.

Twikit uses X's unofficial web interface. [Twikit's own account guidance](https://github.com/d60/twikit/blob/main/ToProtectYourAccount.md)
warns that an account may be limited or suspended. The worker reuses one session
and checks every five minutes instead of logging in repeatedly. A separate X
reader account is safer for your personal account, but the setup accepts the X
account you choose.

On **your PC**, open PowerShell in the Mintly directory and run:

```powershell
python -m pip install twikit==2.3.3
python tools/create_x_session.py
```

Enter your X login identifiers and password only at the local prompts. Twikit
may prompt for a verification code. The helper checks that the resulting session
can read @lakzonevn, then saves it to
`C:\Users\USER\.ssh\mintly-x-cookies.json`. It never writes your password to
disk. If a session already exists and has expired, rerun with `--replace`.

Tell Codex only **“the X session file is ready”**. Do not paste or attach the
cookie file or password. Codex can transfer the file over SSH to
`/home/ubuntu/Mintly/shared/x-cookies.json`, set mode 600, redeploy the worker,
and verify source status. The file is mounted read-only into the worker and is
not distributed to Mintly users or the API container.
