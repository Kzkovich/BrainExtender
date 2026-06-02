#!/bin/bash
# First-time VPS setup. Run once as root on 62.3.12.2
set -e

DOMAIN="brain.kzkovich.ru"
REPO="git@github.com:YOUR_GITHUB_USER/brain-expander.git"
APP_DIR="/opt/brain-expander"

echo "=== Brain Expander — VPS Setup ==="

# Clone repo
if [ ! -d "$APP_DIR" ]; then
    git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

# Create .env from template
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  Edit $APP_DIR/.env and add your tokens, then run:"
    echo "   cd $APP_DIR && docker compose up -d --build"
    echo ""
fi

# Nginx config
cp deploy/nginx.conf /etc/nginx/sites-available/brain.kzkovich.ru
ln -sf /etc/nginx/sites-available/brain.kzkovich.ru /etc/nginx/sites-enabled/

# SSL
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m kzkovich@gmail.com

nginx -t && systemctl reload nginx

# Add deploy user SSH key dir
mkdir -p ~/.ssh && chmod 700 ~/.ssh

echo "=== Setup complete! ==="
echo "Next: fill in .env, then: docker compose up -d --build"
