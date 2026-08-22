# HAMD signing and trust operations

## Independent trust domains

Release signing, Secure Boot v2, ESP-IDF flash encryption, fleet policy,
portal identity, API-client CAs, MQTT trust and release-server trust are
independent. Never copy one private key into another role. The device contains
public verification material only; release, Secure Boot and fleet-policy
private keys remain off-device.

## Release-signing rotation

1. Back up the current offline key and record its public-key fingerprint.
2. Generate a replacement on an offline or hardware-backed signing host.
3. Build a transition core signed by the old release key which provisions a
   bounded trust set containing both old and new public keys.
4. Confirm that core on the test device and verify rollback/recovery.
5. Sign the next universal release with the new key and verify installation.
6. After the fleet is confirmed on the transition core, ship a second core
   that removes the old public key. Retain the old private key offline only for
   recovery images whose documented policy still permits it.

HAMD v2 alpha currently stores one update verification key. Therefore steps 3
to 6 require a purpose-built transition core; do not overwrite the only key on
a field device without a tested USB recovery path.

## Secure Boot rotation

ESP32-S3 Secure Boot key digest changes are eFuse operations and are not normal
OTA maintenance. Follow the ESP-IDF key-revocation flow only after validating
the chip's remaining trusted digest slots on sacrificial hardware. Preserve a
factory image signed by every still-trusted key. Never revoke the final usable
digest remotely.

## Fleet-policy rotation

Fleet policy signing is deliberately online and lower privilege than release
signing: it can select already signed releases but cannot create executable
firmware. Back up `/data/fleet-signing-key.pem` from the Home Assistant add-on.
To rotate it, download the new raw public key, install it as
`.fleet-verification-key` through an authenticated administrator workflow,
verify a no-op signed policy, and only then remove the old add-on key backup.

## Compromise response

- Disable automatic activation and stop active rollout cohorts.
- Revoke affected API/fleet client certificates immediately.
- Preserve device events, add-on events, SBOM, provenance and artifact hashes.
- Use the last known-good signed factory image and documented USB recovery when
  release or Secure Boot trust is uncertain.
- Rotate user/MQTT/Wi-Fi credentials separately; they do not repair a signing
  key compromise.
