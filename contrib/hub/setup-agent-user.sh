#!/usr/bin/env bash
# Create a low-privilege agents user on a development hub (Linux).
# Read it, then run once as root ON THE HUB:
#   sudo EXPECTED_HOST=<hub hostname> bash setup-agent-user.sh
# Optional: AGENT_USER (default kilo), OWNER_USER (default $SUDO_USER), AGENT_ROOT (default /srv/agents).
# Idempotent: re-running only fixes what is missing. It never deletes anything.
set -euo pipefail

AGENT_USER=${AGENT_USER:-kilo}
OWNER_USER=${OWNER_USER:-${SUDO_USER:-}}
AGENT_ROOT=${AGENT_ROOT:-/srv/agents}

[ "$(uname -s)" = Linux ] || { echo "refusing: Linux hub only" >&2; exit 1; }
[ -n "${EXPECTED_HOST:-}" ] || { echo "set EXPECTED_HOST=<hub hostname> (guards against running on the wrong machine)" >&2; exit 1; }
[ "$(hostname)" = "$EXPECTED_HOST" ] || { echo "refusing: this is $(hostname), not $EXPECTED_HOST" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
[ -n "$OWNER_USER" ] && id "$OWNER_USER" >/dev/null || { echo "set OWNER_USER" >&2; exit 1; }

# 1. User: own group, bash, no sudo, no docker, password locked (ssh keys only).
if ! id "$AGENT_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash --user-group "$AGENT_USER"
  echo "created user $AGENT_USER"
fi
passwd --lock "$AGENT_USER" >/dev/null
for g in docker sudo adm lxd; do
  if id -nG "$AGENT_USER" | tr ' ' '\n' | grep -qx "$g"; then
    gpasswd --delete "$AGENT_USER" "$g" >/dev/null; echo "removed $AGENT_USER from $g"
  fi
done

# 2. Work area owned by the agents user; the owner reads it through the agents group.
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 2750 "$AGENT_ROOT"
if ! id -nG "$OWNER_USER" | tr ' ' '\n' | grep -qx "$AGENT_USER"; then
  usermod --append --groups "$AGENT_USER" "$OWNER_USER"
  echo "added $OWNER_USER to group $AGENT_USER (log out and back in)"
fi

# 3. ssh: the owner's authorized keys also open the agents user (attach: ssh <agent>@hub -t screen -x <session>).
home_a=$(getent passwd "$AGENT_USER" | cut -d: -f6)
home_o=$(getent passwd "$OWNER_USER" | cut -d: -f6)
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 700 "$home_a/.ssh"
dst=$home_a/.ssh/authorized_keys; touch "$dst"
if [ -f "$home_o/.ssh/authorized_keys" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    grep -qxF "$line" "$dst" || echo "$line" >> "$dst"
  done < "$home_o/.ssh/authorized_keys"
fi
chown "$AGENT_USER:$AGENT_USER" "$dst"; chmod 600 "$dst"

# 4. Isolation checks: all must be denied for the agents user.
fail=0
check_denied() {
  if sudo -u "$AGENT_USER" -H bash -c "$2" >/dev/null 2>&1; then echo "PROBLEM: $AGENT_USER can $1"; fail=1
  else echo "ok: $AGENT_USER cannot $1"; fi
}
check_denied "use docker"              "docker ps"
check_denied "use sudo"                "sudo -n true"
check_denied "read the owner's home"   "ls $home_o"
check_denied "write to /usr/local/bin" "touch /usr/local/bin/.agent-write-test"
[ "$fail" -eq 0 ] && echo "all isolation checks passed" || { echo "fix the PROBLEM lines above"; exit 2; }

cat <<EOF

Next, as $AGENT_USER (from your workstation: ssh -t $AGENT_USER@<hub> ...), install user-level tools:
  curl -LsSf https://astral.sh/uv/install.sh | sh          # uv/uvx (tests)
  curl -fsSL https://kilo.ai/cli/install | bash            # Kilo CLI (or: npm install -g @kilocode/cli)
  echo '[ -d "\$HOME/.kilo/bin" ] && PATH="\$HOME/.kilo/bin:\$PATH"' >> ~/.profile   # non-interactive shells
  kilo auth login                                          # the agents user's own credentials
  git clone <repo-url> $AGENT_ROOT/<repo>
As $OWNER_USER, so that git accepts repositories owned by $AGENT_USER:
  git config --global --add safe.directory '$AGENT_ROOT/*'
Record every step in your host record.
EOF
