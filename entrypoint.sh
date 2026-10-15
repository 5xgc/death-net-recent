#!/bin/sh
set -e

# ---------- sshd config ----------
mkdir -p /var/run/sshd /root/.ssh

if [ -z "$SSH_ROOT_PASSWORD" ]; then
    SSH_ROOT_PASSWORD="changeme-$(head -c 6 /dev/urandom | base64 | tr -d '/+=')"
    echo "[ssh] no SSH_ROOT_PASSWORD env — generated: $SSH_ROOT_PASSWORD"
fi

echo "root:${SSH_ROOT_PASSWORD}" | chpasswd

# allow root login with password
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/^#\?Port .*/Port 2222/' /etc/ssh/sshd_config

ssh-keygen -A

# optional: inject your pubkey for key-based login
if [ -n "$SSH_PUBKEY" ]; then
    echo "$SSH_PUBKEY" > /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
fi

# auto-run officialv3.py on interactive ssh login
if [ "$AUTORUN" = "1" ]; then
    cat >> /root/.profile <<'EOF'
if [ -n "$SSH_CONNECTION" ] && [ -z "$DEATH_LAUNCHED" ]; then
    export DEATH_LAUNCHED=1
    cd /app && python3 /app/officialv3.py
fi
EOF
fi

/usr/sbin/sshd -D -e &
SSHD_PID=$!
echo "[ssh] sshd up on :2222"

# ---------- ngrok tcp tunnel ----------
if [ -z "$NGROK_AUTHTOKEN" ]; then
    echo "[ngrok] NGROK_AUTHTOKEN not set — ssh will be unreachable from outside"
else
    ngrok config add-authtoken "$NGROK_AUTHTOKEN"

    if [ -n "$NGROK_TCP_ADDR" ]; then
        # reserved tcp address, format: "1.tcp.ngrok.io:12345"
        ngrok tcp --remote-addr "$NGROK_TCP_ADDR" 2222 --log=stdout &
    else
        ngrok tcp 2222 --log=stdout &
    fi
    echo "[ngrok] tcp tunnel starting -> 2222"
fi

# ---------- http health server for render + uptimerobot ----------
exec python3 /app/health.py
