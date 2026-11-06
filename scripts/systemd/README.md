# Ollama bridge for Docker (user systemd units)

Ollama keeps listening on `127.0.0.1:11434`. Containers reach the host through
`host.docker.internal`, which resolves to the Docker host gateway
(`172.17.0.1` on a default Linux setup). These units expose Ollama on
`172.17.0.1:11434` only — loopback stays the canonical address and the LAN
interface never listens on 11434.

`systemd-socket-proxyd` forwards each accepted connection to
`127.0.0.1:11434`. No sudo is required.

## Install

```sh
install -Dm644 ollama-bridge.socket  ~/.config/systemd/user/ollama-bridge.socket
install -Dm644 ollama-bridge.service ~/.config/systemd/user/ollama-bridge.service
systemctl --user daemon-reload
systemctl --user enable --now ollama-bridge.socket
```

## Verify

```sh
ss -ltn | grep 11434                     # 127.0.0.1 and 172.17.0.1 only
systemctl --user is-active ollama-bridge.socket
docker run --rm --network bridge \
  --add-host host.docker.internal:host-gateway \
  --entrypoint /bin/sh postgres:17-alpine \
  -c 'wget -q -O - http://host.docker.internal:11434/api/tags | head -c 80'
```

## Notes

- `FreeBind=true` lets the socket bind before `docker0` exists at boot, so
  there is no race with `docker.service`. The socket becomes reachable once
  `172.17.0.1` is assigned.
- `loginctl show-user "$USER" -p Linger` should report `Linger=yes` so the
  user manager starts at boot without an interactive login.
- The container side needs `extra_hosts: ["host.docker.internal:host-gateway"]`;
  see the git-ignored `docker-compose.override.yml`.
- Inside containers, `CUSTOM_API_URL` must be
  `http://host.docker.internal:11434/v1`, not `127.0.0.1`.
