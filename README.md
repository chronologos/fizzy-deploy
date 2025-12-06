# fizzy-deploy

Deploy [Fizzy](https://github.com/basecamp/fizzy) on a local machine via Docker + systemd, served over Tailscale.

## Architecture

```
Browser (HTTPS)
    ↓
Tailscale Serve (TLS termination)
    ↓ https://fizzy.your-tailnet.ts.net:443
localhost:3100
    ↓
Docker container (fizzy:local)
    ↓ Thruster → Puma
Rails app
```

## Prerequisites

- Docker
- Tailscale (connected to your tailnet)
- Fizzy repo cloned locally (default: `../fizzy` relative to this repo)

## Setup

### 1. Create Tailscale Service

1. Go to https://login.tailscale.com/admin/services
2. Create a service named `fizzy`
3. Set endpoint to `tcp:443`

### 2. Configure Secrets

```bash
cp .secrets.example.json .secrets.json
# Edit .secrets.json with your values
```

### 3. Deploy

```bash
sudo python3 deploy.py
```

## Usage

```bash
sudo python3 deploy.py              # Initial deploy
sudo python3 deploy.py --rebuild    # Rebuild image and restart
sudo python3 deploy.py --restart    # Restart without rebuilding
sudo python3 deploy.py --stop       # Stop the service
sudo python3 deploy.py --status     # Check service status
sudo python3 deploy.py --logs       # View container logs
```

## Updating Fizzy

```bash
cd /path/to/fizzy
git pull
cd /path/to/fizzy-deploy
sudo python3 deploy.py --rebuild
```

## Configuration

See [CLAUDE.md](CLAUDE.md) for detailed configuration options including:
- Email/SMTP setup (SendGrid)
- Tailscale Service configuration
- Secrets management
- Troubleshooting

## License

MIT
