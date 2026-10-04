# Local Webhook Tunneling Guide: Exposing DispatchEngine for Live Twilio SMS

Twilio requires a public HTTPS endpoint to deliver incoming SMS and webhook payloads to your local development server running at `http://localhost:8000`.

This guide outlines how to expose your local instance securely using **Cloudflare Tunnel** (`cloudflared`) or **ngrok**, and how to configure your Twilio phone number.

---

## Option 1: Cloudflare Tunnel (`cloudflared`) [Recommended]

Cloudflare Tunnel provides free, permanent HTTPS URLs without session time limits or interstitial warning pages.

### 1. Install `cloudflared`
- **Windows (winget)**:
  ```powershell
  winget install --id Cloudflare.cloudflared
  ```
- **Windows (Chocolatey)**:
  ```powershell
  choco install cloudflared
  ```
- **macOS (Homebrew)**:
  ```bash
  brew install cloudflared
  ```

### 2. Start the Tunnel
Ensure your local server is running on port 8000, then execute:
```bash
cloudflared tunnel --url http://localhost:8000
```

### 3. Copy Your Public URL
`cloudflared` will print a public HTTPS URL:
```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://alpha-bravo-charlie.trycloudflare.com                                             |
+--------------------------------------------------------------------------------------------+
```

---

## Option 2: `ngrok`

### 1. Install `ngrok`
- **Windows (winget)**:
  ```powershell
  winget install ngrok.ngrok
  ```
- **macOS / Linux**:
  ```bash
  brew install ngrok/ngrok/ngrok
  ```
- **npm**:
  ```bash
  npm install -g ngrok
  ```

### 2. Start the Tunnel
```bash
ngrok http 8000
```
Copy the forwarding HTTPS URL (e.g., `https://abc123-free.ngrok-free.app`).

---

## Configuring Twilio Phone Number

Once your tunnel is running, link your tenant's webhook URL in the Twilio Console:

1. Open the [Twilio Console](https://console.twilio.com/).
2. Navigate to **Phone Numbers** -> **Manage** -> **Active Numbers**.
3. Click on the active phone number you wish to assign to this tenant.
4. Scroll down to the **Messaging Configuration** section.
5. Under **"A MESSAGE COMES IN"**:
   - Change dropdown to **Webhook**.
   - Set the URL to your tunnel address + tenant webhook path:
     ```
     https://<YOUR-TUNNEL-DOMAIN>/api/v1/webhooks/twilio/sms?tenant_slug=<TENANT-SLUG>
     ```
     *Example:*
     ```
     https://alpha-bravo-charlie.trycloudflare.com/api/v1/webhooks/twilio/sms?tenant_slug=acme-roofing
     ```
   - Set the HTTP method to **HTTP POST**.
6. Click **Save Configuration** at the bottom of the page.

---

## Simulating / Testing Live Webhook Deliveries

You can test that your tunnel is reachable and accurately triggering the qualification and dispatch engine by sending a simulated carrier payload:

### PowerShell:
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/webhooks/twilio/sms?tenant_slug=acme-roofing" `
  -Method POST `
  -ContentType "application/x-www-form-urlencoded" `
  -Body @{
    From = "+15551234567"
    To = "+15559876543"
    Body = "Emergency: Major roof leak during the storm, need immediate technician dispatch!"
    MessageSid = "SM_TEST_LIVE_$(Get-Random)"
  }
```

### cURL:
```bash
curl -X POST "http://localhost:8000/api/v1/webhooks/twilio/sms?tenant_slug=acme-roofing" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=%2B15551234567&To=%2B15559876543&Body=Emergency%3A+Major+roof+leak+flooding+our+warehouse%21&MessageSid=SM_TEST_LIVE_999"
```

Expected Response:
```xml
<?xml version="1.0" encoding="UTF-8"?><Response></Response>
```

---

## Monitoring Live Ingestion

Open the Operator Dashboard in your browser:
```
http://localhost:8000/dashboard?tenant_slug=acme-roofing
```
Every incoming text message will immediately show:
1. Contact phone number and timestamp
2. Urgency classification (`EMERGENCY`, `HIGH`, `MEDIUM`, `LOW`, `SPAM`)
3. Gemini LLM qualification score and reasoning
4. Automated dispatch route and Twilio SMS alert status
