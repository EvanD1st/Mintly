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

The PC needs `twikit==2.3.3`. It is already installed in the current Mintly
workspace; on another PC, install it with `python -m pip install twikit==2.3.3`.

As of 2026-09-30, Twikit 2.3.3 fails on X's page scripts ([upstream issue](https://github.com/d60/twikit/issues/408)).
The browser-cookie route also failed its authenticated read check, so it is
disabled. **Do not copy X session cookies from DevTools or retry the login.**
No X session has been saved or installed on Ubuntu. The automatic @lakzonevn
reader is unavailable until Twikit is compatible with X again or an official
X API integration is configured. Admin imports remain available; Mintly will
not replace the feed with another source.

Once Twikit is fixed and verified, the password login route checks startup
before requesting any login details:

```powershell
python tools/create_x_session.py
```

Enter your X login identifiers and password only at the local prompts if using
that route after compatibility is restored. Twikit may prompt for a verification
code. The helper never writes your password to disk. If a saved session expires,
rerun with `--replace`.

Tell Codex only **“the X session file is ready”**. Do not paste or attach the
cookie file or password. Codex can transfer the file over SSH to
`/home/ubuntu/Mintly/shared/x-cookies.json`, set mode 600, redeploy the worker,
and verify source status. The file is mounted read-only into the worker and is
not distributed to Mintly users or the API container.
