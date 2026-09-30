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

Twikit 2.3.3 currently fails on X's anonymous page before it can request a
password ([upstream issue](https://github.com/d60/twikit/issues/408)). If you
are already signed in to X in Chrome, use that browser session instead of
retrying the password:

1. Open your signed-in `https://x.com` tab in Chrome (not Password Manager).
2. Press F12, open **Application → Storage → Cookies → https://x.com**.
   [Chrome's guide](https://developer.chrome.com/docs/devtools/application/cookies)
   explains how to view individual cookie values.
3. Find the cookie named `auth_token` and copy its **Value**. In a PowerShell
   window in the Mintly directory, run `python tools/create_x_session.py --from-browser`
   and paste the value at the hidden `auth_token` prompt. Repeat for `ct0`.
   Do not paste either value in chat, a screenshot, or a browser console.
4. The helper checks read access to @lakzonevn and saves the verified session
   to `C:\Users\USER\.ssh\mintly-x-cookies.json`. Afterward, clear the
   clipboard with `Set-Clipboard -Value ''`.

The original password login route remains available if Twikit's anonymous
startup works again. It now checks that startup before asking for a password:

```powershell
python tools/create_x_session.py
```

Enter your X login identifiers and password only at the local prompts if using
that route. Twikit may prompt for a verification code. The helper never writes
your password to disk. If a saved session expires, rerun with `--replace`.

Tell Codex only **“the X session file is ready”**. Do not paste or attach the
cookie file or password. Codex can transfer the file over SSH to
`/home/ubuntu/Mintly/shared/x-cookies.json`, set mode 600, redeploy the worker,
and verify source status. The file is mounted read-only into the worker and is
not distributed to Mintly users or the API container.
