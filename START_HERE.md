# Mintly development handoff

> Historical design handoff. The app has since been implemented and deployed.
> Read [README.md](README.md) for the current account, wallet, and data behavior.

1. Extract this folder into your project workspace.
2. Open the workspace in Antigravity.
3. Paste the contents of `Mintly_Antigravity_Prompt.md` into a new agent task and ask it to implement the project. Ensure the agent can read `design/mintly-splash-reference.html`.
4. Open the design reference in a browser to inspect the approved splash and tap-through app flow. Its optional icon/style resources may need internet access. Everything in this reference is a simulation; it makes no API calls and sends no transactions.
5. Configure any required accounts or credentials locally when the implementation reaches those integrations. Do not paste X cookies, wallet secrets, or signing credentials into an AI chat.
6. When Antigravity finishes, open the same repository in Codex and use `Mintly_Codex_Review_Prompt.md` for an independent review.

The main prompt specifies Python/FastAPI, Flutter Android, Twikit as an experimental no-paid-X-API source, manual import fallback, supported OpenSea eligibility, and a server-operated mint queue. It requires honest demo/live separation and forbids mainnet execution during implementation.

No production code or APK is included here. This package contains the implementation brief, review brief, and approved UI reference.
