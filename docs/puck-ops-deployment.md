# Puck bridge on ops: deployment and Home rollout runbook (P-HOME-01)

This runbook installs `puck_bridge` on the household host `ops` as
`hermes-puck-bridge.service`, in Home transport only, and orders the Puck Home
rollout. It adds no bridge behaviour. Spec:
`_bmad-output/implementation-artifacts/spec-p-home-01-deploy-puck-bridge-on-ops.md`.

Every step carries a label:

- **[exercised]**: run in this repository, with the evidence named.
- **[smoke-only]**: run once in the disposable Linux smoke below, with
  systemd shimmed. Not yet run against the real ops install.
- **[unexercised]**: not yet run anywhere against the real ops install,
  Home, the network or the Puck. Running this runbook needs separate
  operational authorization; writing it does not grant any.

There is no direct-Hermes fallback. Legacy direct mode and the voice-session
endpoint are retired; the deploy tool refuses any transport other than `home`.
If Home is unavailable, the Puck stays unavailable.

## Known blocker

The Puck can only admit a new Home claim with calibrated proximity evidence
from a trusted hardware provider (P-4). Production wiring passes no provider,
so after a claim is retired, the bridge restarts with a non-active record, or
Home restarts, every wake is refused. Until the provider exists, a deployed
bridge serves only its initially configured claim. Do not work around this.

## What the tooling does

`scripts/deploy_puck_bridge.py deploy|rollback`:

- builds from an existing `vX.Y.Z` release tag (`git archive`, test suite,
  wheel) whose source contains `puck_bridge/home_admission.py`;
- installs `/opt/hermes-puck-bridge/releases/<sha>` with the `voice` extra,
  under a lock (`~/.hermes-puck-bridge-deploy.lock`), refusing to overwrite
  an existing release; a failure before activation (precondition, venv or
  `pip install`) removes the release directory this run created and the
  staging upload, so the same tag can be retried;
- removes any stale `current.next`/`previous.next` link, then
  switches the `current` symlink atomically, restarts the unit and waits for
  `systemctl is-active` plus a TCP connection to `<bind>:<port>`;
- on restart or health failure restores the previous release and its unit
  (or, on a first deploy, stops and removes the new unit) and deletes the
  failed release so the tag can be retried;
- on success enables the unit and keeps the old release as `previous`;
- uses only `hermes-puck-bridge.service`. It never touches
  `hermes-home-browser.service`, its state or pairing, or any other unit.

The unit runs as `hermes-puck` with `StateDirectory=hermes-puck-bridge`
(0700), `UMask=0077`, `NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome`, `PrivateTmp` and `ReadWritePaths=/var/lib/hermes-puck-bridge`.
`HOME`, `XDG_CACHE_HOME` and `HF_HOME` point into the state directory, so the
claim-recovery records (`~/.hermes-relay-tui/home-claim-state/`) and the
Whisper model cache persist across restarts. Credentials come only from
`EnvironmentFile=/var/lib/hermes-puck-bridge/bridge.env`; an `ExecStartPre`
check stops the unit with a clear message when that file is missing, not a
regular file, not owned by `hermes-puck` or not mode 0600. The command line is:

```
/opt/hermes-puck-bridge/current/venv/bin/python -m puck_bridge \
  --transport home --host <bind> --port <port> --home-url <wss://…/api/v1/bridge/ws>
```

Arguments: `--bind` must be one private LAN IPv4 address (not `0.0.0.0`,
loopback or Tailscale `100.64.0.0/10`); `--port` defaults to 8766 and refuses
8765 (legacy) and 8875 (browser appliance); `--home-url` must be an exact
`wss://<host>/api/v1/bridge/ws`.

**[exercised]** Repository checks: `venv/bin/pytest tests/test_deploy_puck_bridge.py`
renders and checks the unit, validates arguments, runs the embedded remote
script locally against temporary directories with fake `sudo`/`systemctl`
(deploy, overwrite refusal, failed `pip install` cleanup and retry,
automatic rollback on restart and health failure, first-deploy failure,
rollback, stale `current.next`, preconditions with staging cleanup, lock) and
runs the `ExecStartPre` check against a temporary env file. These
repository checks contact no host. The fakes include GNU `readlink -f` semantics, which BSD readlink
had hidden (see below).

**[smoke-only]** 2026-10-18 smoke in a throwaway, unprivileged Ubuntu 26.04
container: Python 3.14, GNU `mv` 9.7, uutils `stat` 0.10.0, util-linux
`flock` 2.41.3, and real `sudo`. Ops is also Ubuntu 26.04, but runs uutils
`stat` 0.8.0 (GNU `mv` 9.7 and `flock` 2.41.3 match). The container ran on
ops's Docker under the owner's 2026-10-18 deploy authorization. It used no
host port and no host mount, and it changed no host unit, file or service.
It was removed afterwards. The real `deploy_puck_bridge.py` CLI ran over SSH.
Home was a synthetic local `wss://home.test` endpoint with a throwaway CA.
The env file held synthetic values created by following Install steps 1-2;
no household credentials were used. Observed:

- a missing `bridge.env` was refused before anything was installed, and the
  staging upload was removed;
- a first deploy whose Home connection failed health-checked, stopped and
  removed its unit and release;
- a first deploy (v0.13.0) and an upgrade (v0.13.1) switched `current` and
  `previous` correctly, listened on the bind address, enabled the unit and
  left no staging directory;
- the bridge opened `conversation.open` with a correctly authenticated
  `Device` header;
- `rollback` swapped `current` and `previous` and the bridge listened again;
- `systemctl restart` and a container restart brought the enabled unit back
  with the claim-recovery record unchanged (same sha256). After a restart
  the bridge only listens: because a record is present, `server.main` does
  not reconnect to Home. Only the first start's `conversation.open` proves
  Home contact;
- `systemd-analyze verify` accepted the unit.

The smoke found and fixed two defects:

- On a first deploy, GNU `readlink -f` of the missing `current` made
  `previous` point at `current`. CI on Linux failed for the same reason.
- A failed `scp` stranded the remote staging directory.

**Not exercised:** PID-1 systemd and a host reboot. Unprivileged Docker
mounts the cgroup filesystem read-only, so systemd as PID 1 failed with
`Failed to allocate manager object: Read-only file system`. Running it would
need `--privileged`, `CAP_SYS_ADMIN` with AppArmor disabled, or a host
cgroup mount on a shared household host. So the restart steps used a
smoke-only `systemctl` shim that executes the unit's
User/Environment/EnvironmentFile/ExecStartPre/ExecStart, and the reboot was
approximated by a container restart. Real systemd sandboxing
(`ProtectSystem`, `StateDirectory` creation and so on) and boot ordering
remain unverified until a VM or the first ops install.

## Prerequisites

1. **[unexercised]** Code prerequisites STD-6, P-4 and P-6 are in a published
   release tag. Use that tagged checkout to run the helper.
2. **[unexercised]** Rollout prerequisites: the Puck is paired in Home under
   3-P-2's ordered flow (needs hermes-relay-home
   `HOME-NW-17-room-device-admission`) and the P-4 trusted provider exists.
   The tooling can be installed before these; the household rollout cannot.
3. **[unexercised]** Choose a stable ops LAN address (DHCP reservation) and
   confirm port 8766 is still free: `ss -ltn 'sport = :8766'`.
4. **[unexercised]** On ops: `python3.14`, `flock`, and the PortAudio runtime
   needed by the `voice` extra (`sudo apt install libportaudio2`).

## Install

1. **[smoke-only]** Create the service user and private state directory:

   ```bash
   sudo useradd --system --home-dir /var/lib/hermes-puck-bridge --shell /usr/sbin/nologin hermes-puck
   sudo install -d -o hermes-puck -g hermes-puck -m 0700 /var/lib/hermes-puck-bridge
   ```

2. **[smoke-only, synthetic values]** Create the env file yourself, on the host, without
   putting values in shell history, the repository or any log:

   ```bash
   sudo install -o hermes-puck -g hermes-puck -m 0600 /dev/null /var/lib/hermes-puck-bridge/bridge.env
   sudoedit /var/lib/hermes-puck-bridge/bridge.env
   ```

   Keys (values come from the Home pairing and the Puck firmware secrets):
   `PUCK_DEVICE_TOKEN`, `HOME_DEVICE_CREDENTIAL`, `HOME_DEVICE_ID`,
   `HOME_CONVERSATION_HANDLE`, and `HOME_WAKE_MAPPING_ID` when Home has more
   than one active mapping. The deploy tool checks only the file's presence,
   owner and mode; it never reads or writes values. Do not reuse the browser
   appliance's pairing.

3. **[smoke-only]** From the tagged checkout on the operator machine:

   ```bash
   venv/bin/python scripts/deploy_puck_bridge.py deploy --ops-host ops \
     --bind <ops-lan-ip> --home-url wss://<home-host>/api/v1/bridge/ws --tag vX.Y.Z
   ```

4. **[smoke-only]** Verify: `systemctl status hermes-puck-bridge`,
   `ss -ltnp 'sport = :8766'` shows only `<ops-lan-ip>`, and
   `systemctl status hermes-home-browser` is unchanged.
5. **[smoke-only]** Confirm the first start reached Home. The journal must
   show `puck bridge connecting through Home` followed by `listening`, with
   no `HomeBridgeTransportError`. **If the first start failed to reach Home**
   (or any first install failed after the unit started), clear the
   claim-recovery record before retrying:
   `sudo rm -rf /var/lib/hermes-puck-bridge/.hermes-relay-tui/home-claim-state`.
   The bridge writes an `active` record before its first Home connect, and
   later starts never reopen Home while a record exists. Without this step a
   retry reports "active and listening" without ever connecting to Home.

## Start, stop, restart

- **[smoke-only]** `sudo systemctl restart hermes-puck-bridge` — the unit
  returns without manual action (`Restart=on-failure`, enabled at boot).
- **[smoke-only]** After a restart or reboot, confirm the claim-recovery file
  persists under `/var/lib/hermes-puck-bridge/.hermes-relay-tui/home-claim-state/`
  (mode 0600). Per the blocker above, new claims stay refused after restart.
- **[unexercised]** `sudo systemctl stop hermes-puck-bridge` stops the bridge;
  the Puck then reports unavailable.

## Upgrade

**[smoke-only]** Run `deploy` with the new tag. A failed restart or health
check restores the previous release automatically and exits non-zero.

## Rollback

**[smoke-only]** Run `rollback` with the same `--bind`, `--port` and
`--home-url` the previous release was installed with:

```bash
venv/bin/python scripts/deploy_puck_bridge.py rollback --ops-host ops \
  --bind <ops-lan-ip> --home-url wss://<home-host>/api/v1/bridge/ws
```

It refuses when no previous release exists or its saved unit differs. Rolling
back does not clear the claim-recovery record. Clear it as in Install step 5
only if the rolled-back release must open a fresh Home claim.

## Removal

**[unexercised]**

```bash
sudo systemctl disable --now hermes-puck-bridge
sudo rm /etc/systemd/system/hermes-puck-bridge.service
sudo systemctl daemon-reload
sudo rm -rf /opt/hermes-puck-bridge
# Only when retiring the Puck bridge for good (this also removes bridge.env
# and the claim-recovery record):
# sudo rm -rf /var/lib/hermes-puck-bridge
```

Delete `/var/lib/hermes-puck-bridge` (credentials, claim records, model
cache) only after revoking the device in Home (3-P-6).

## Firmware flash

**[unexercised]** Follow `firmware/respeaker-lite/README.md`, "Build &
Flashing", with the Home transport substitution so wakes stay closed until
the bridge confirms admission:

```bash
venv-firmware/bin/esphome -s puck_home_transport true compile firmware/respeaker-lite/respeaker-lite.yaml
venv-firmware/bin/esphome -s puck_home_transport true upload firmware/respeaker-lite/respeaker-lite.yaml --device respeaker-lite.local
```

Point the firmware's bridge address at `<ops-lan-ip>:8766`. The 2026-09-12
build's secrets are lost; decide on a rollback image before flashing.

## Ordered rollout

Each live check records its evidence in the owning story, not here.

1. **[unexercised]** Install and verify the bridge (above). Evidence: this story.
2. **[unexercised]** Pair the Puck in Home and apply Room, credential and Wake
   Mapping. Evidence: 3-P-2 and hermes-relay-home `HOME-NW-17-room-device-admission`.
3. **[unexercised]** Flash Home-transport firmware (above).
4. **[unexercised]** P-7 controlled hardware check (P-7 spec, Verification).
   Evidence: P-7.
5. **[unexercised]** STD-6 deferred external gate (STD-6 spec, Tasks:
   "Deferred external gate"). Evidence: STD-6.
6. **[unexercised]** Restart and reboot persistence on ops. Evidence: this story.
7. **[unexercised]** Puck row of hermes-relay-home MIG-09 AC-5, including
   renewal and revocation. Evidence: MIG-09.

If a step fails, stop the bridge or roll back. Never switch the Puck or the
bridge to direct Hermes.
