# IoT-MD v3.0.0-alpha.8 test note

## Purpose

Alpha 8 is a portal usability test release. It keeps the Alpha 7 native ABI 4
platform boundary and corrects two issues observed on the installed device:
manual upgrades did not expose overall progress, and Safari filtered the Wi-Fi
network suggestions to the already-entered SSID.

## Included

- A current-stage indicator plus an overall step counter, progress track and
  persistent stage list for `.iotapp`, `.iotcore` and `.iotuni` workflows.
- Browser byte progress that does not depend on Safari setting
  `lengthComputable`, plus a render opportunity between acknowledged chunks.
- A detected-network select control which always lists every returned SSID and
  preserves the current network when it is not visible in the latest scan.
- Manual SSID entry in the same field area, with a direct return to detected
  networks, in both the first-boot wizard and the authenticated Network page.
- Three bounded 20-second startup Wi-Fi attempts with short backoff and station
  cleanup before the established recovery path is latched.

## Expected behavior

The byte-upload stage may still complete in well under a second on a local
network. That is valid. The page must nevertheless retain the completed upload
step and continue to show the active write, verification, staging or pairing
step and its position in the complete workflow.

The Wi-Fi status count represents visible scan results. Opening the detected
network selector must show all of those distinct SSIDs, not only the current
SSID. A stored SSID which is no longer visible is additionally retained as
`(current)` and is not included in the visible-network count.

## Safety and rollback

The release sequence is `2713`. Use
`universal-3.0.0-alpha.8.iotuni` for complete application/core version pairing.
Alpha 8 does not enable any previously unqualified native capability. The v2.5
compatibility runtime and Alpha 7 recovery safeguards remain in place.
