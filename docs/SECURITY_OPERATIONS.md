# HAMD security operations

## Trust domains

Release signing, Secure Boot, flash encryption, fleet policy, portal identity,
API-client CAs, MQTT trust and release-server trust are independent. Never
reuse a private key between domains. Devices contain public verification
material; release, Secure Boot and fleet private keys remain off-device.

## Rotation

### Release signing

1. Generate and back up a replacement offline P-256 key.
2. Ship an old-key-signed transition core trusting both public keys.
3. Verify update, recovery and rollback on qualification hardware.
4. Sign the next universal release with the new key.
5. After fleet confirmation, ship a core that removes the old public key.

Never overwrite the only trusted release key without a tested USB recovery
path.

### Secure Boot

Secure Boot digest changes are eFuse operations, not ordinary OTA maintenance.
Follow the ESP-IDF revocation process only after checking remaining digest slots
on sacrificial hardware. Never revoke the last usable digest remotely.

### Fleet policy and client certificates

Back up the fleet add-on key separately. Provision a new public key, verify a
signed no-op policy and only then retire the old key. Revoke and replace
compromised API/fleet client certificates immediately.

## Incident response

1. Disable automatic activation and stop rollouts.
2. Revoke affected client certificates and credentials.
3. Preserve device/add-on events, artifact hashes, SBOM and provenance.
4. Use the last known-good signed factory image and USB recovery when platform
   trust is uncertain.
5. Rotate Wi-Fi, MQTT and portal credentials independently.
