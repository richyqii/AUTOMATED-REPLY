# VIN WhatsApp Sales Automation

**Current task: activate the existing Meta virtual test number.** Follow [docs/META_TEST_SETUP.md](docs/META_TEST_SETUP.md) first. Keep the existing WhatsApp Business number unchanged; the public YouTube link does not use the virtual test sender.

Real Python/FastAPI integration with Meta's official WhatsApp Cloud API for **VIN Corporate Services Sdn Bhd**.

YouTube public preview → customer opens WhatsApp → customer presses **Send** → signed Meta webhook → automatic purchase instructions → Gumroad checkout → training video.

The runtime sends HTTPS requests to `https://graph.facebook.com/{version}/{phone-number-id}/messages`. There is no conversation simulator or WhatsApp Web/browser automation. Tests replace outbound HTTP with test transports so they cannot message customers.

## Future public YouTube link

[Ask VIN about E-Invoice training on WhatsApp](https://wa.me/60124182788?text=Hi%2C%20I%20want%20to%20know%20more%20about%20your%20E-Invoice%20training.)

```text
https://wa.me/60124182788?text=Hi%2C%20I%20want%20to%20know%20more%20about%20your%20E-Invoice%20training.
```

The message is `Hi, I want to know more about your E-Invoice training.` The customer can edit it and **must manually press Send**. Opening this link does not trigger a webhook or a reply. **Do not publish this as an automated-sales link until a separately approved production connection is working.** The current Meta virtual-number test uses a different destination.

## What is ready and what needs your account

The application, persistent queue, staff commands, Docker configuration, VS Code launcher, and automated tests are included. Local development uses Python 3.12 or later; the prepared workspace has `.venv` and a Python runtime under ignored `.tools`.

**Live testing requires your Meta credentials, the virtual test number, an allowed test recipient, and a reachable HTTPS callback.** A phone number by itself is not API authorization. No live WhatsApp delivery is claimed until the virtual-number test below passes.

## 1. Use the existing Meta virtual test sender

The Meta app is **EInvoice Training Test**. Its virtual sender is **+1 555 634 5224**, Phone Number ID **1469646646227844**, and WABA ID **935834989406383**. These IDs are already in the private `.env`. See [the exact remaining test setup steps](docs/META_TEST_SETUP.md). You will use the temporary token from Step 1, App Secret from App settings, and your ngrok account token.

The public VIN link above points to the existing WhatsApp Business number. The test sender has its own test chat; no change to the existing business number is part of this test.

## 2. Configure the workspace

The private `.env` already exists in this workspace. **Edit it in place; do not copy `.env.example` over it.** The example file is for fresh installations. Update these fields locally:

| Variable | Value |
| --- | --- |
| `META_ACCESS_TOKEN` | Your token authorized for this WABA/number |
| `META_APP_SECRET` | Your Meta app secret |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta's ID for the virtual test sender during setup |
| `WHATSAPP_EXPECTED_NUMBER` | Virtual test sender display number, international digits only |
| `WHATSAPP_SENDER_MODE` | Keep `test` for the current virtual-number setup |
| `META_APP_ID` / `WHATSAPP_BUSINESS_ACCOUNT_ID` | IDs for test WABA subscription checks |
| `NGROK_AUTHTOKEN` | Optional when `ngrok config add-authtoken` already saved the token locally |
| `WHATSAPP_VERIFY_TOKEN` | Already generated locally; copy its value to Meta's webhook form |
| `META_GRAPH_VERSION` | Defaults to pinned `v25.0`; use a supported version confirmed in Meta's dashboard/changelog |
| `DATABASE_PATH` | Defaults to `data/vin.sqlite3`; keep this on persistent local storage |

For a fresh installation only, generate a webhook verify token with PowerShell:

```powershell
$tokenBytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($tokenBytes)
[Convert]::ToBase64String($tokenBytes)
$rng.Dispose()
```

Paste the generated value into `.env` and Meta's verification-token field. Keep `.env` private. This workspace's token is already generated. Startup rejects missing values and example placeholders; there is no insecure signature-verification bypass.

Dependencies are already installed in this prepared workspace. To recreate them on another machine with Python 3.12+ installed:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
```

Alternatively, with [uv](https://docs.astral.sh/uv/) installed, run `uv sync --locked --extra dev`. The workspace-local executable is `.\.tools\uv\uv.exe`; it can recreate the prepared environment with that same `sync` command. `uv.lock`, `requirements.txt`, and `requirements-dev.txt` pin dependencies for reproducible installs.

Check that the token and number ID resolve to your **virtual test number** (read-only, sends nothing):

```powershell
& .\.venv\Scripts\python.exe -m app.manage check-meta
```

## 3. Start FastAPI

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Or select the `.venv` Python interpreter in VS Code and use the **VIN WhatsApp webhook** F5 launch configuration.

The equivalent server command is:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Visit `http://127.0.0.1:8000/` for the customer link and `http://127.0.0.1:8000/healthz` for local readiness. Readiness checks storage and the worker, not Meta authentication. The server starts its persistent-queue worker automatically. Access logging is disabled to avoid logging the verification token in the GET query string.

## 4. Expose the webhook over HTTPS

Meta cannot reach `localhost`. Use the installed ngrok client with its saved local configuration or an optional `.env` authtoken:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_tunnel.ps1
& .\.venv\Scripts\python.exe scripts\show_callback.py
```

Keep both the Python service and tunnel running. If ngrok gives you `https://your-host.ngrok-free.app`, your callback is:

```text
https://your-host.ngrok-free.app/webhook
```

In **WhatsApp → Configuration → Webhooks**, set that callback and your `WHATSAPP_VERIFY_TOKEN`, then verify and save. Subscribe to the **`messages`** field for incoming messages and delivery statuses. Ensure the app is subscribed to the **test WABA** containing your virtual sender; a verified callback alone is not a WABA subscription. See [the test setup guide](docs/META_TEST_SETUP.md) for exact clicks and commands.

If needed, the WABA app-subscription endpoint is `POST /{WABA-ID}/subscribed_apps` with the appropriate authorized token. Follow Meta's official setup guide for your account rather than confusing the WABA ID with the Phone Number ID.

The GET handshake returns the raw `hub.challenge`. Every POST must have a valid `X-Hub-Signature-256` computed using your App Secret over the exact raw body. The app accepts only events matching the configured Phone Number ID. Your tunnel/proxy must preserve request bodies and the signature header. Suppress query strings in proxy access logs as well.

## 5. Run the virtual-number acceptance test

1. Run `app.manage check-meta` and confirm the returned number is **+1 555 634 5224**. Follow [the virtual-number test steps](docs/META_TEST_SETUP.md).
2. Add your personal WhatsApp number to Meta's allowed test recipients. From that account, message the **virtual test sender** with the E-Invoice enquiry and press **Send** yourself. The public YouTube link points to VIN's existing number and is not part of this test.
3. Confirm the test recipient receives the complete welcome message, five purchase steps, Gumroad URL, and HELP instruction. The exact text lives in [app/messages.py](app/messages.py).
4. Run the status command below. `sent` means Meta accepted the outbound message, not that it reached the handset. `delivery_status=delivered` or `read` records the corresponding later webhook. Confirm actual receipt on the handset.
5. Send `HELP`. Confirm the acknowledgment arrives and the support request appears in `help-requests`. Send a follow-up: it is saved for staff without another sales pitch. Send `START` to resume automation.
6. Confirm the Gumroad purchase URL opens the intended product. A checkout or paid-access test requires your separate Gumroad seller setup. Do not treat a Meta sample webhook as proof of real-message delivery.

## Gumroad training delivery

Purchase URL: https://einvoicemy.gumroad.com/l/e-invoice-training-2026

In your Gumroad seller account, publish the product, configure the training video/content, and verify the receipt/content access experience. Ensure the customer-facing **Watch Your Training** instruction matches the configured purchase experience. This repository cannot create or validate that label, your payment setup, or private video access without your Gumroad account. Gumroad handles checkout, receipts and paid access; the Python service does not collect payment details or unlock videos.

## Staff support and delivery monitoring

Run from this repository root with the same `.env` and database as the server:

```powershell
& .\.venv\Scripts\python.exe -m app.manage status
& .\.venv\Scripts\python.exe -m app.manage help-requests
# Substitute the CUSTOMER'S WhatsApp ID, not VIN's number:
& .\.venv\Scripts\python.exe -m app.manage resume 60111111111
```

HELP creates a persistent support request and pauses sales automation for that customer. Follow-up text is also saved; media is represented by its type without downloading it. **Staff must monitor this local queue** and respond through your authorized human inbox/support process. There is no external staff notification or agent inbox integration in this project. The HELP acknowledgment also offers VIN's phone number for direct assistance. `resume` resolves requests and allows future incoming messages to trigger replies; it sends nothing and does not override an opt-out.

`STOP` silently opts the customer out and suppresses queued replies. `START` opts back in, resolves the handoff, and sends the training instructions. Unrelated messages and media receive no automatic reply. E-Invoice, eInvoice, e invoicing, and e-invois text variants trigger the sales response while automation is enabled.

The local SQLite database stores customer WhatsApp IDs, message IDs, queue state and support text. Restrict access to it and `.env`. Do not commit these files. Use a SQLite-aware backup while running, or stop the service before copying its database files; keep backups private. Retain inbox IDs long enough to deduplicate Meta retries.

## Reliability and operating limits

- Validated events are committed before HTTP 200. Storage failure returns 503 so Meta can retry. The full webhook batch is handled in one transaction.
- Incoming message IDs are unique, preventing the same webhook delivery from creating multiple reply jobs across restarts. Distinct customer messages may each receive a reply.
- One worker sends sequentially, approximately one reply per second. Use one service process/replica with a persistent local SQLite volume. Do not put SQLite on a shared/network filesystem. For larger deployments, migrate the queue to a server database and dedicated workers.
- Connection failures known to happen before sending and explicit HTTP 429 responses retry with backoff, up to five total attempts. Other 4xx errors need configuration review. Replies expire before the 24-hour customer service window closes; this project does not send templates outside that window.
- Read/write timeouts, server errors, malformed success responses, and interrupted in-flight jobs become `uncertain` rather than automatically resending a possibly accepted reply. Expired in-flight leases are detected after 120 seconds. Delivery callbacks can reconcile these using the supplied callback identifier. Staff should investigate remaining uncertain jobs; exactly-once remote delivery cannot be guaranteed across a network failure.
- A STOP/HELP that arrives after a request is already in flight cannot recall that request. Pending replies are suppressed.
- Check queue status regularly for `failed`, `uncertain`, `expired`, or delivery failure codes. `/healthz` alone does not prove messages can be delivered.

For continuous operation, deploy on an always-on host behind HTTPS, retain `data/`, and restart the service on failure. Closing VS Code, sleeping the PC, or losing a development tunnel interrupts local replies. A changed tunnel URL must also be updated in Meta.

## Docker deployment option

With Docker installed and `.env` configured:

```powershell
docker compose up --build -d
docker compose exec whatsapp python -m app.manage status
docker compose exec whatsapp python -m app.manage help-requests
```

The container runs without root privileges, keeps its SQLite database in the `vin-data` named volume, and binds port 8000 to host loopback. Put an HTTPS reverse proxy or tunnel in front. Do not run `docker compose down -v` unless you intend to delete queue/support data. Docker configuration is provided; it requires validation on your deployment host.

## Tests

```powershell
# Only needed if you installed runtime dependencies without dev tools:
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\ruff.exe check .
& .\.venv\Scripts\ruff.exe format --check .
```

Tests cover signing, verification, batch handling, routing, persistent deduplication, exclusive queue claims, HELP/STOP/START, API request shape, retry limits, uncertain outcomes, delivery reconciliation and expired reply windows. They require no Meta credentials and send no real WhatsApp messages. They verify application behavior; the real-phone test verifies the external integration.

## Official references

- [WhatsApp click-to-chat link format](https://faq.whatsapp.com/425247423114725/)
- [Meta-maintained WhatsApp Cloud API collection: prerequisites, credentials and permissions](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
- [Meta webhook setup and reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview)
- [Meta text message API](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/text-messages)
- [WhatsApp Business Messaging Policy: 24-hour window and human escalation](https://business.whatsapp.com/policy)
- [Graph API version changelog](https://developers.facebook.com/docs/graph-api/changelog/)

Meta's dashboard labels and onboarding requirements can change; follow the current instructions for your business account. Meta messaging charges and Gumroad fees may apply.
