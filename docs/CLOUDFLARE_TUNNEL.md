# Hosting Gymnasium on gymnasium.marashi.ai (Cloudflare named tunnel)

`start.sh` boots the Gymnasium app and, when configured, publishes it at
`https://gymnasium.marashi.ai` through a Cloudflare **named** tunnel — no
inbound ports, no public IP. `reset-tunnel.sh` repairs a stale tunnel/DNS
mapping.

The same `start.sh` runs **local-only** when the tunnel env is unset, so
it doubles as the plain dev launcher.

## ⚠️ Security — plaintext auth, publicly reachable

The app authenticates with **plaintext credentials** behind a single
login gate. Once the tunnel is up the app is reachable by anyone on the
internet, so **that login gate is the only thing protecting it.**

- Use a **strong, unique password** for every account (`gymnasium adduser`).
- Treat any account as compromised if its password is reused elsewhere.
- **Optional follow-up:** put **Cloudflare Access** in front of
  `gymnasium.marashi.ai` for a real second factor (SSO / one-time PIN).
  This is recommended but not wired up by these scripts.

## One-time operator setup

These steps need the operator's Cloudflare account and a machine that
stays running. They are **not** done by CI and cannot be done from a
sandbox.

1. **Install cloudflared**

   ```bash
   brew install cloudflared        # macOS
   # or see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
   ```

2. **Log in to Cloudflare** and authorize the `marashi.ai` zone. This
   writes `~/.cloudflared/cert.pem`, which `start.sh` checks for.

   ```bash
   cloudflared tunnel login
   ```

   In the browser that opens, pick the **marashi.ai** zone.

3. **Create a Gymnasium login** (plaintext-auth account):

   ```bash
   gymnasium adduser <username> <password>
   ```

4. **Configure and start**

   ```bash
   cp .env.example .env      # keeps TUNNEL_NAME=gymnasium, APP_HOST=gymnasium.marashi.ai
   ./start.sh
   ```

   On first run `start.sh` creates the `gymnasium` tunnel, routes
   `gymnasium.marashi.ai` to it, writes the ingress config under
   `.runtime/cloudflared.yml`, and runs `cloudflared` in the background.
   It prints both the public URL (`https://gymnasium.marashi.ai`) and the
   local URL. Leave the process running to keep the site up.

## Local-only (no tunnel)

Leave `TUNNEL_NAME` / `APP_HOST` unset (the default `.env.example` sets
them, so either edit `.env` to comment them out, or just run without a
`.env`). `start.sh` then serves the app on `http://localhost:$PORT`
(default `8000`) and starts no tunnel.

```bash
PORT=8000 ./start.sh
```

## Fixing a stale tunnel (Error 1033)

If `gymnasium.marashi.ai` returns **Error 1033** (Argo Tunnel error), the
DNS CNAME is pointing at a tunnel UUID that no longer exists — common
after switching machines. Recreate the tunnel and re-route DNS:

```bash
./reset-tunnel.sh
```

If it reports that an A/AAAA record blocks the route, delete that record
in **dash.cloudflare.com → marashi.ai → DNS → Records** and re-run it.

## How it works

- `start.sh` auto-loads `.env`, boots the app
  (`gymnasium --port $PORT --db $DB --reports $REPORTS --docs-dir $DOCS`,
  falling back to `python3 -m university.server` from a source checkout),
  and waits until it answers on `http://localhost:$PORT/`.
- In tunnel mode it verifies the cloudflared login, creates the tunnel if
  missing, resolves its UUID, checks the per-tunnel credentials file
  (`~/.cloudflared/<uuid>.json`), routes DNS (unless `SKIP_DNS=1`), writes
  an ingress config mapping `APP_HOST → http://localhost:$PORT` with a
  `404` catch-all, and runs `cloudflared` in the background.
- An exit trap kills both the app and `cloudflared`. Logs go under
  `logs/` (`gymnasium.log`, `cloudflared.log`); the generated tunnel
  config lives under `.runtime/`. Both directories are git-ignored.
