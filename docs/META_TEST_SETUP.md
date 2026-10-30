# Meta virtual-number activation for EInvoice Training Test

This is the live-test path for the existing Meta app. **Use Meta's virtual test number as the sender.** Leave +60 12-418 2788 in its WhatsApp Business app and skip production phone registration and payment steps. The public YouTube link still points to VIN's real number, so it cannot use this test integration until a separate, approved production connection exists.

For this app, the virtual test sender is **+1 555 634 5224**, its Phone Number ID is **1469646646227844**, and the test WABA ID is **935834989406383**. These non-secret IDs are already saved locally. The Step 2 production tile may stay incomplete during this virtual-number test; configure its webhook section without registering a production phone.

## What has been prepared locally

- FastAPI `GET /webhook` verifies Meta's challenge using `WHATSAPP_VERIFY_TOKEN`.
- Signed `POST /webhook` accepts WhatsApp message events and queues replies.
- A read-only Meta sender check runs before the server starts and again before the first outbound reply. The displayed sender must match `WHATSAPP_EXPECTED_NUMBER`; test mode rejects VIN's current business number.
- A private `.env` contains a generated Verify Token. It has no working Meta credentials yet.
- ngrok is installed from Microsoft Store. Its authtoken can be saved in ngrok's local configuration file or in the private `.env`.

## A. Put account values into the local `.env`

Open [`.env`](../.env) in VS Code. Copy values from **Meta Developers → EInvoice Training Test → WhatsApp → Basic setup → Step 1: Try it out** (the menu may also be called **API Setup**):

| Local field | Where to find the value |
| --- | --- |
| `META_ACCESS_TOKEN` | Temporary Access Token on Step 1; it expires and is for testing |
| `WHATSAPP_PHONE_NUMBER_ID` | **Phone Number ID** for the Meta virtual sender |
| `WHATSAPP_EXPECTED_NUMBER` | The virtual sender's displayed number, international digits only, without `+` |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | **WhatsApp Business Account ID** of the test WABA, if shown |

In **App settings → Basic**, copy **App ID** into `META_APP_ID` and reveal **App Secret** to copy into `META_APP_SECRET`. Keep `WHATSAPP_SENDER_MODE=test`. The already generated `WHATSAPP_VERIFY_TOKEN` stays in `.env`; use its value in Meta's webhook form. Do not put secrets in chat, screenshots, Git, or the Meta callback URL.

Create or sign in to a free [ngrok account](https://dashboard.ngrok.com/), open **Your Authtoken**, and configure ngrok locally. If you used `ngrok config add-authtoken`, leave `NGROK_AUTHTOKEN` blank in `.env`; the launcher uses ngrok's saved configuration. You can alternatively save the token as `NGROK_AUTHTOKEN` in `.env`. Meta and ngrok each need their own credentials.

Run these read-only checks in the VS Code PowerShell terminal:

```powershell
& .\.venv\Scripts\python.exe scripts\check_setup.py
& .\.venv\Scripts\python.exe -m app.manage check-meta
```

`check-meta` should show the **virtual test number**, not 60124182788. If it fails, stop and correct the token, Phone Number ID, or virtual sender number. The check sends no message.

## B. Start the server and HTTPS tunnel

In VS Code terminal 1:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

The server should report it is listening on `127.0.0.1:8000`. The launcher first runs `check-meta` and refuses to start when the configured sender is wrong.

In terminal 2:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_tunnel.ps1
```

This starts ngrok using its saved local configuration or the private `.env` token and exposes port 8000. Keep both terminals running. In terminal 3, get the **exact active callback**:

```powershell
& .\.venv\Scripts\python.exe scripts\show_callback.py
```

The printed URL has the form `https://<your-active-ngrok-host>/webhook`. The hostname is assigned when ngrok starts, so it cannot be known before the tunnel is running. If ngrok changes its hostname, update Meta's callback. The Meta callback is the ngrok URL plus `/webhook`, not the `wa.me` customer link.

## C. Verify Meta webhook and subscribe to messages

In [Meta Developers](https://developers.facebook.com/apps/) open **EInvoice Training Test → WhatsApp use case → Basic setup → Step 2: Production setup → Configure webhooks**. Depending on Meta's dashboard layout this may be **WhatsApp → Configuration**.

1. In **Callback URL**, paste the exact URL printed by `show_callback.py`.
2. In **Verify token**, paste the private `WHATSAPP_VERIFY_TOKEN` value from `.env`. Leave a client-certificate setting off unless your account already uses one.
3. Click **Verify and save**. Meta should make a GET request to the running server. If it fails, check the server and ngrok terminals and confirm the token has no extra spaces.
4. In the **Webhook fields** list, locate **messages** and click **Subscribe**. This field carries both incoming messages and delivery statuses. A verified callback alone is insufficient.
5. Check the test WABA's app subscription:

   ```powershell
   & .\.venv\Scripts\python.exe -m app.manage check-subscription
   ```

   If it says the test WABA is not subscribed, run this once, then recheck:

   ```powershell
   & .\.venv\Scripts\python.exe -m app.manage subscribe-test-waba
   & .\.venv\Scripts\python.exe -m app.manage check-subscription
   ```

The subscription command first checks that the WABA contains the configured Phone Number ID and works only in test mode. It neither registers a phone nor adds billing. [Meta's Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-d0e227d1-e520-4b12-a8f6-32657a52d26e) confirms the `subscribed_apps` endpoint.

## D. Real virtual-number message test

On **Step 1: Try it out**, add your own personal WhatsApp number as an allowed test recipient and complete its verification. Send Meta's sample message from the virtual number to that recipient if needed to open a chat. From that personal WhatsApp account, **reply to the virtual number** with:

```text
Hi, I want to know more about your E-Invoice training.
```

The real incoming message must appear in the server's SQLite queue, and the virtual number must send the full Gumroad purchase reply through Meta's Cloud API. Inspect local outcomes:

```powershell
& .\.venv\Scripts\python.exe -m app.manage status
```

`sent` only means Meta accepted the API request. Confirm the actual reply on the recipient phone, and preferably a `delivered` or `read` status. A dashboard-generated sample webhook is useful for checking the callback but does not prove that the real-message loop works. The real test number cannot be used to prove delivery to customers through the public VIN `wa.me` link.

## Failure clues

| Symptom | First check |
| --- | --- |
| Meta **Verify and save** fails | Server `/healthz`, ngrok terminal, exact `/webhook` URL, exact Verify Token |
| Meta test webhook works but real message does not appear | **messages** field subscription, test WABA app subscription, recipient allowlist, test-number ID |
| `check-meta` fails | Temporary token expiry/permissions, Phone Number ID, displayed virtual number |
| Job is `failed` | `app.manage status` error code; `sender_check_*` means sending was blocked before any reply; `http_*_meta_*` comes from the send API |
| Job is `uncertain` | Network outcome or server interruption; inspect delivery callback and recipient phone before any manual retry |
| Meta accepted reply but phone received nothing | Recipient allowlist, Meta delivery status, test number, account restrictions |

The temporary Meta token expires; replace it locally when needed. Ngrok and the Python server must stay running during the test. This is a development test, not an always-on customer service deployment.

If `app.manage status` shows `sender_check_http_401_meta_190`, the token failed before the Cloud API send request. Replace `META_ACCESS_TOKEN` in `.env`, restart the FastAPI server, confirm `app.manage check-meta` succeeds, then requeue only those safe failures:

```powershell
& .\.venv\Scripts\python.exe -m app.manage retry-expired-token-replies
```

The worker will send only if the customer's 24-hour reply window is still open. Confirm actual delivery on the recipient phone; a requeued or accepted API job alone does not prove it arrived.
