#!/usr/bin/env python3
"""
Fizzy deployment script.
Deploys Fizzy as a Docker container managed by systemd, accessible via Tailscale.

Usage:
    sudo python3 deploy.py              # Initial deploy
    sudo python3 deploy.py --rebuild    # Rebuild image and restart
    sudo python3 deploy.py --restart    # Restart without rebuilding
    sudo python3 deploy.py --stop       # Stop the service
    sudo python3 deploy.py --status     # Show service status
    sudo python3 deploy.py --logs       # Show container logs
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

# Configuration
DEPLOY_DIR = Path(__file__).parent.resolve()
FIZZY_REPO = DEPLOY_DIR.parent / "fizzy"  # Expects fizzy repo as sibling directory
IMAGE_NAME = "fizzy:local"
VOLUME_NAME = "fizzy_storage"
SERVICE_NAME = "fizzy"
SECRETS_FILE = DEPLOY_DIR / ".secrets.json"
SERVICE_FILE = Path("/etc/systemd/system/fizzy.service")


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


def check_prerequisites() -> None:
    """Verify all prerequisites are met."""
    print("\n[1/7] Checking prerequisites...")

    # Check running as root (needed for systemd)
    if os.geteuid() != 0:
        print("Error: This script must be run with sudo")
        sys.exit(1)
    print("  - Running as root: OK")

    # Check Docker
    result = run(["docker", "info"], check=False, capture=True)
    if result.returncode != 0:
        print("Error: Docker is not running or not installed")
        sys.exit(1)
    print("  - Docker: OK")

    # Check Tailscale
    result = run(["tailscale", "status"], check=False, capture=True)
    if result.returncode != 0:
        print("Error: Tailscale is not connected")
        sys.exit(1)
    print("  - Tailscale: OK")

    # Check Fizzy repo exists
    if not (FIZZY_REPO / "Dockerfile").exists():
        print(f"Error: Fizzy repo not found at {FIZZY_REPO}")
        sys.exit(1)
    print(f"  - Fizzy repo: OK ({FIZZY_REPO})")


def get_tailscale_ip() -> str:
    """Get the Tailscale IPv4 address."""
    print("\n[2/7] Getting Tailscale IP...")
    result = run(["tailscale", "ip", "-4"], capture=True)
    ip = result.stdout.strip()
    print(f"  - Tailscale IP: {ip}")
    return ip


def build_image() -> None:
    """Build the Docker image from the Fizzy repo."""
    print("\n[3/7] Building Docker image...")
    run(["docker", "build", "-t", IMAGE_NAME, str(FIZZY_REPO)])
    print("  - Image built successfully")


def create_volume() -> None:
    """Create the Docker volume for persistent storage."""
    print("\n[4/7] Creating Docker volume...")
    # Check if volume exists
    result = run(
        ["docker", "volume", "inspect", VOLUME_NAME],
        check=False,
        capture=True,
    )
    if result.returncode == 0:
        print(f"  - Volume '{VOLUME_NAME}' already exists")
    else:
        run(["docker", "volume", "create", VOLUME_NAME])
        print(f"  - Volume '{VOLUME_NAME}' created")


def generate_secrets() -> dict:
    """Generate or load secrets."""
    print("\n[5/7] Managing secrets...")

    if SECRETS_FILE.exists():
        print(f"  - Loading existing secrets from {SECRETS_FILE}")
        with open(SECRETS_FILE) as f:
            return json.load(f)

    print("  - Generating new secrets...")

    # Generate SECRET_KEY_BASE
    secret_key_base = secrets.token_hex(64)
    print("  - Generated SECRET_KEY_BASE")

    # Generate VAPID keys using the Docker image
    print("  - Generating VAPID keys (this may take a moment)...")
    ruby_code = 'keys = WebPush.generate_key; puts({public: keys.public_key, private: keys.private_key}.to_json)'
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-e", "SECRET_KEY_BASE=dummy",
            IMAGE_NAME,
            "bin/rails", "runner", ruby_code
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  - Error generating VAPID keys: {result.stderr}")
        sys.exit(1)
    vapid_keys = json.loads(result.stdout.strip())
    print("  - Generated VAPID keys")

    secrets_data = {
        "SECRET_KEY_BASE": secret_key_base,
        "VAPID_PUBLIC_KEY": vapid_keys["public"],
        "VAPID_PRIVATE_KEY": vapid_keys["private"],
    }

    # Save secrets
    with open(SECRETS_FILE, "w") as f:
        json.dump(secrets_data, f, indent=2)
    os.chmod(SECRETS_FILE, 0o600)
    print(f"  - Secrets saved to {SECRETS_FILE}")

    return secrets_data


def create_systemd_service(tailscale_ip: str, secrets_data: dict) -> None:
    """Create the systemd service file."""
    print("\n[6/7] Creating systemd service...")

    service_content = f"""[Unit]
Description=Fizzy Rails Application
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=5

# Stop and remove any existing container before starting
ExecStartPre=-/usr/bin/docker stop {SERVICE_NAME}
ExecStartPre=-/usr/bin/docker rm {SERVICE_NAME}

# Start the container (bind to localhost, tailscale serve handles external access)
ExecStart=/usr/bin/docker run --rm \\
  --name {SERVICE_NAME} \\
  -p 127.0.0.1:3100:80 \\
  -v {VOLUME_NAME}:/rails/storage \\
  -v {DEPLOY_DIR}/smtp_initializer.rb:/rails/config/initializers/smtp.rb:ro \\
  -e SECRET_KEY_BASE={secrets_data["SECRET_KEY_BASE"]} \\
  -e VAPID_PUBLIC_KEY={secrets_data["VAPID_PUBLIC_KEY"]} \\
  -e VAPID_PRIVATE_KEY={secrets_data["VAPID_PRIVATE_KEY"]} \\
  -e SOLID_QUEUE_IN_PUMA=true \\
  -e SMTP_ADDRESS={secrets_data.get("SMTP_ADDRESS", "")} \\
  -e SMTP_PORT={secrets_data.get("SMTP_PORT", "587")} \\
  -e SMTP_DOMAIN={secrets_data.get("SMTP_DOMAIN", "")} \\
  -e SMTP_USERNAME={secrets_data.get("SMTP_USERNAME", "")} \\
  -e SMTP_PASSWORD={secrets_data.get("SMTP_PASSWORD", "")} \\
  -e MAILER_FROM_ADDRESS={secrets_data.get("MAILER_FROM_ADDRESS", "")} \\
  {IMAGE_NAME}

# Stop the container
ExecStop=/usr/bin/docker stop {SERVICE_NAME}

[Install]
WantedBy=multi-user.target
"""

    with open(SERVICE_FILE, "w") as f:
        f.write(service_content)
    print(f"  - Service file written to {SERVICE_FILE}")

    # Reload systemd
    run(["systemctl", "daemon-reload"])
    print("  - systemd daemon reloaded")


def enable_and_start() -> None:
    """Enable and start the systemd service."""
    print("\n[7/8] Enabling and starting service...")

    run(["systemctl", "enable", SERVICE_NAME])
    print(f"  - Service '{SERVICE_NAME}' enabled")

    run(["systemctl", "restart", SERVICE_NAME])
    print(f"  - Service '{SERVICE_NAME}' started")


def setup_tailscale_serve() -> str:
    """Configure Tailscale Serve for HTTPS termination.

    Prerequisites:
    - Create a Tailscale Service named "fizzy" in admin console
    - Set endpoint to tcp:443
    """
    print("\n[8/8] Configuring Tailscale Serve...")

    # Set up tailscale serve with dedicated service hostname
    # Note: Admin console must have fizzy service with endpoint tcp:443
    run(["tailscale", "serve", "--service", "svc:fizzy", "--bg", "--https=443", "127.0.0.1:3100"])
    print("  - Tailscale Serve configured (fizzy service, HTTPS:443 -> localhost:3100)")

    # Get the tailnet name from tailscale status
    result = run(["tailscale", "status", "--json"], capture=True)
    status = json.loads(result.stdout)
    dns_name = status.get("Self", {}).get("DNSName", "").rstrip(".")
    # Extract tailnet from machine DNS name and construct service URL
    parts = dns_name.split(".")
    if len(parts) >= 3:
        tailnet = ".".join(parts[1:])
        return f"fizzy.{tailnet}"
    return dns_name


def show_status() -> None:
    """Show the service status."""
    run(["systemctl", "status", SERVICE_NAME, "--no-pager"], check=False)


def show_logs() -> None:
    """Show container logs."""
    run(["docker", "logs", "-f", SERVICE_NAME], check=False)


def stop_service() -> None:
    """Stop the service."""
    print("Stopping service...")
    run(["systemctl", "stop", SERVICE_NAME])
    print("Service stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Fizzy to this machine")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild image and restart")
    parser.add_argument("--restart", action="store_true", help="Restart without rebuilding")
    parser.add_argument("--stop", action="store_true", help="Stop the service")
    parser.add_argument("--status", action="store_true", help="Show service status")
    parser.add_argument("--logs", action="store_true", help="Show container logs")
    args = parser.parse_args()

    # Handle simple commands
    if args.status:
        show_status()
        return
    if args.logs:
        show_logs()
        return
    if args.stop:
        stop_service()
        return

    # Full deploy or restart
    check_prerequisites()
    tailscale_ip = get_tailscale_ip()

    if not args.restart:
        build_image()

    create_volume()
    secrets_data = generate_secrets()
    create_systemd_service(tailscale_ip, secrets_data)
    enable_and_start()
    dns_name = setup_tailscale_serve()

    print("\n" + "=" * 50)
    print("Deployment complete!")
    print("=" * 50)
    print(f"\nFizzy is now accessible at: https://{dns_name}")
    print("\nUseful commands:")
    print(f"  sudo python3 {__file__} --status   # Check status")
    print(f"  sudo python3 {__file__} --logs     # View logs")
    print(f"  sudo python3 {__file__} --restart  # Restart service")
    print(f"  sudo python3 {__file__} --rebuild  # Rebuild and restart")
    print(f"  tailscale serve status             # Check Tailscale Serve config")


if __name__ == "__main__":
    main()
