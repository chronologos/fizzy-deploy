# Fizzy Deploy

Deployment scripts for running [Fizzy](https://github.com/basecamp/fizzy) via Docker + systemd, served over Tailscale.

## Architecture

```
Browser (HTTPS)
    ↓
Tailscale Serve (TLS termination)
    ↓ https://fizzy.<your-tailnet>.ts.net:443
localhost:3100
    ↓
Docker container (fizzy:local)
    ↓ Thruster → Puma
Rails app (port 80 inside container)
```

## Files

- `deploy.py` - Main deployment script
- `.secrets.json` - Generated secrets (SECRET_KEY_BASE, VAPID keys) - auto-created on first deploy

## Usage

```bash
# Initial deploy (builds image, generates secrets, starts service)
sudo python3 deploy.py

# Rebuild image and restart (after git pull in fizzy repo)
sudo python3 deploy.py --rebuild

# Restart without rebuilding
sudo python3 deploy.py --restart

# Stop the service
sudo python3 deploy.py --stop

# Check service status
sudo python3 deploy.py --status

# View container logs
sudo python3 deploy.py --logs
```

## Updating Fizzy

```bash
cd ../fizzy
git pull
cd ../fizzy-deploy
sudo python3 deploy.py --rebuild
```

## Configuration

| Setting | Value |
|---------|-------|
| Fizzy repo | `../fizzy` (sibling directory) |
| Docker image | `fizzy:local` |
| Docker volume | `fizzy_storage` (persists SQLite DB + uploads) |
| Container port | `127.0.0.1:3100` → container port 80 |
| Tailscale Service | `fizzy.<your-tailnet>.ts.net` |
| systemd service | `fizzy.service` |

## Secrets

Stored in `.secrets.json` (auto-generated on first deploy, owned by root):

**Required:**
- `SECRET_KEY_BASE` - Rails secret key
- `VAPID_PUBLIC_KEY` - Web push notification public key
- `VAPID_PRIVATE_KEY` - Web push notification private key

**Email (optional but needed for login):**
- `SMTP_ADDRESS` - SMTP server (e.g., `smtp.sendgrid.net`)
- `SMTP_PORT` - SMTP port (typically `587`)
- `SMTP_DOMAIN` - Your domain
- `SMTP_USERNAME` - SMTP username (e.g., `apikey` for SendGrid)
- `SMTP_PASSWORD` - SMTP password/API key
- `MAILER_FROM_ADDRESS` - Verified sender email address

## Email Configuration (SendGrid)

Fizzy uses passwordless magic link authentication, which requires email.

### Setup

1. Get SendGrid API key from https://sendgrid.com
2. Verify a sender identity in SendGrid (Settings → Sender Authentication)
3. Update secrets:

```bash
sudo python3 -c "
import json
with open('.secrets.json') as f:
    s = json.load(f)
s.update({
    'SMTP_ADDRESS': 'smtp.sendgrid.net',
    'SMTP_PORT': '587',
    'SMTP_DOMAIN': 'yourdomain.com',
    'SMTP_USERNAME': 'apikey',
    'SMTP_PASSWORD': 'SG.your-api-key-here',
    'MAILER_FROM_ADDRESS': 'verified-sender@yourdomain.com'
})
with open('.secrets.json', 'w') as f:
    json.dump(s, f, indent=2)
"
```

4. Restart: `sudo python3 deploy.py --restart`

### Files

- `smtp_initializer.rb` - Mounted into container at `/rails/config/initializers/smtp.rb`
- Configures Rails ActionMailer with SMTP settings from environment variables

### Debugging email issues

```bash
# Check failed jobs
docker exec fizzy bin/rails runner "SolidQueue::FailedExecution.last(5).each { |f| puts f.error['message'] }"

# Check pending jobs
docker exec fizzy bin/rails runner "puts SolidQueue::Job.where(finished_at: nil).count"

# Verify SMTP config in Rails
docker exec fizzy bin/rails runner "puts ActionMailer::Base.smtp_settings.inspect"
```

## Troubleshooting

```bash
# Check systemd service
sudo systemctl status fizzy

# Check container logs
docker logs fizzy

# Check Tailscale Serve config
tailscale serve status

# Restart everything
sudo python3 deploy.py --restart

# Full rebuild
sudo python3 deploy.py --rebuild
```

## Dependencies

- Docker
- Tailscale (connected to tailnet)
- Tailscale Service "fizzy" created in admin console

## Tailscale Service Setup

Before running deploy.py, create the Tailscale Service in the admin console:

1. Go to https://login.tailscale.com/admin/services
2. Create a new service named `fizzy`
3. **Important**: Set endpoint to `tcp:443` (must match the port used in tailscale serve)
4. The service will get its own IP and hostname: `fizzy.<your-tailnet>.ts.net`

The deploy script then runs:
```bash
sudo tailscale serve --service svc:fizzy --bg --https=443 127.0.0.1:3100
```

This makes Tailscale:
1. Accept HTTPS on port 443 at the fizzy service IP
2. Terminate TLS (auto-provisions certificate)
3. Proxy to localhost:3100 (the Docker container)

### Manual Tailscale Serve Commands

```bash
# Check current config
tailscale serve status --json

# Set up serve (after admin console service is created)
sudo tailscale serve --service svc:fizzy --bg --https=443 127.0.0.1:3100

# Clear config
sudo tailscale serve clear svc:fizzy

# May need to restart tailscaled after admin console changes
sudo systemctl restart tailscaled
```

### Troubleshooting Tailscale Service

If the service IP doesn't respond:
- Verify endpoint in admin console matches the port (tcp:443 for HTTPS)
- Restart tailscaled: `sudo systemctl restart tailscaled`
- Check serve status: `tailscale serve status --json`
