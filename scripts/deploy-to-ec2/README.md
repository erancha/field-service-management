# Deploying to EC2

> # ⚠️ PENDING — NOT YET RUN END TO END
>
> **This deployment has never been executed.** No EC2 instance, Elastic IP, security group, key pair,
> hosted zone, or certificate has been created by it yet, and no domain has been registered.
> Everything below describes intended behaviour that so far is verified only statically.
>
> **Verified without deploying:** both nginx edges pass `nginx -t` (localhost and TLS), the compose
> overlay merges to the expected ports and environment, `run-instances` passes `--dry-run`, the AWS
> queries return correct results, all modules pass `bash -n`, and the read-only `--check-domain`
> command runs live.
>
> **Unverified — expect the first run to surface problems here:** cloud-init installing Docker,
> BuildKit driving the remote daemon over SSH, the arm64 SPA build on the box, the real ACME
> challenge and certificate installation, and unattended renewal (which cannot be observed for ~60
> days).
>
> Treat the first deploy as a debugging session, not a release. Start with `FSM_ACME_STAGING=1`.

The same stack the [README](../../README.md) runs locally also runs publicly on a single ARM EC2 box,
driven from your machine through a **remote Docker context**. Each role is served on its own hostname
over HTTPS:

| App | URL |
|---|---|
| Technician | `https://tech.<your-domain>` |
| Customer | `https://app.<your-domain>` |
| Back office | `https://admin.<your-domain>` |

Everything is driven by [`scripts/deploy-to-ec2/start.sh`](start.sh); run it
with `-h` for the full command list and the environment overrides (instance type, disk size, naming).

## Getting a domain

```bash
# 1. find a name — read-only, checks the requested ending plus cheaper ones
FSM_DOMAIN=example.com ./scripts/deploy-to-ec2/start.sh --check-domain

# 2. buy it through Route 53 — charges the AWS account
FSM_DOMAIN=example.com ./scripts/deploy-to-ec2/start.sh --register-domain
```

Registration is a separate command from the deploy on purpose: it spends money and cannot be undone,
so it should never happen as a side effect of shipping code. It prints the price and asks for typed
confirmation, enables auto-renew (a lapsed domain takes the site down with it) and WHOIS privacy, and
creates the delegated hosted zone the deploy then needs.

ICANN requires genuine registrant details — copy
[`scripts/domain-contact.example.json`](../domain-contact.example.json) to
`scripts/domain-contact.json` (gitignored) and fill it in. **The registrant email receives a
verification link that must be clicked within 15 days, or ICANN suspends the domain** — that click is
the one step no API can do for you. Registering through the Route 53 console instead works equally
well; the deploy only requires that a delegated hosted zone exists.

## Deploying

```bash
FSM_DOMAIN=example.com FSM_ACME_EMAIL=you@example.com ./scripts/deploy-to-ec2/start.sh
```

This launches (or reuses) the box, attaches an Elastic IP, points the three DNS records at it, builds
the images **on the box**, starts the stack, obtains a certificate, and prints the four Google
redirect URIs to register on the OAuth client.

Docker Compose is a client-side plugin, so the build runs on the box's daemon — natively arm64, no
registry and no cross-compilation — and no copy of the repo is left behind. Compose also reads
`backend/.env` locally and passes the values as container environment, so secrets are never written
to the box's disk.

On a first run, pass `FSM_ACME_STAGING=1` to issue from Let's Encrypt's staging CA. Staging
certificates are untrusted by browsers but do not consume the production rate limit, which locks out
five failed issuances per hour — and a first run is exactly where DNS or firewall problems surface.

## How the edge works

nginx serves the three hostnames on 443 and the ACME challenge on 80, using
[`nginx/public.conf.template`](../../nginx/public.conf.template) — rendered over the per-port localhost
config at container start when `FSM_DOMAIN` is set, so one image serves both local and public runs.
Certificates live in a Docker volume, are issued once by the deploy script, and are renewed by a
certbot service; nginx reloads periodically to pick up a renewed one.

HTTPS is not cosmetic here: Google accepts a plain-http redirect URI only for loopback, so a public
deployment must terminate TLS or no one can sign in. Two settings in
[`scripts/deploy-to-ec2/docker-compose.ec2.yml`](docker-compose.ec2.yml)
follow from that:

- Each role runs with `--forwarded-allow-ips`, because uvicorn otherwise trusts `X-Forwarded-Proto`
  only from `127.0.0.1` — nginx reaches it from a compose network address. Without it the derived
  OAuth callback would be `http://` and Google would reject it.
- `APP_ENV=prod` marks the session cookie `https_only`, so the browser never puts it on the wire in
  clear — including on a first plain-http request that arrives before the redirect.

Postgres and Redis stay bound to the box's loopback interface. Reach the database with `--db-tunnel`,
which forwards it to `localhost:15432`.

## Operating it

The existing helpers take `--context`, so there is no second set of commands to learn:

```bash
./scripts/docker-helper.sh --context fsm-ec2 --logs -e backoffice
./scripts/sql-helper.sh    --context fsm-ec2 -tA -c "SELECT count(*) FROM appointment;"
```

Local runs are untouched — every remote command passes `--context` explicitly, so the default Docker
context never moves and `start.sh` and `test.sh` keep using the local daemon.

`--stop` stops the instance (the disk, the data, and the Elastic IP survive, so DNS stays valid),
`--start` brings it back, `--status` reports the instance and the containers, and `--terminate`
destroys it. AWS credentials come from `FSM_AWS_CONFIG`, else `scripts/aws-config.sh` (gitignored),
else the environment.

## Who can sign in, and what it costs

Google sign-in is the only path in, so access is governed by the OAuth consent screen: while it is in
**Testing**, only accounts listed under Audience > Test users can sign in (up to 100), and each sees a
one-time "Google hasn't verified this app" warning. `ADMIN_EMAILS` then governs who reaches the back
office.

Publishing the app opens sign-in to any Google account. Worth weighing before doing so: the triage
chat calls a paid model API on every turn, re-sending the whole conversation, and the code has **no
per-user rate limit** — so open sign-up means unbounded spend. Leaving `ASSIST_MODEL` unset disables
the chat and that cost with it.

Running cost is roughly **$36/month** in eu-central-1 for the default `t4g.medium`: the instance is
about three quarters of it, the rest being the 30 GB gp3 volume, the Elastic IP, the Route 53 hosted
zone, and the domain amortized. `t4g.small` runs the stack too (steady state is around 1 GB resident;
the box's 2 GB swap covers the SPA build) and saves about $14/month. Model API usage is billed
separately and is the only line that varies with traffic.

## Open gaps

- **No backup of the Postgres volume.** `--terminate` is irreversible.
- **No monitoring.** A failed certificate renewal first shows up as a browser warning, though Let's
  Encrypt emails `FSM_ACME_EMAIL` before the certificate actually expires.
