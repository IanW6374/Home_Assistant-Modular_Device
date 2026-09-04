# Host and qualification tooling

Host tools will build and sign the native platform and MicroPython runtime,
assemble the paired universal release, migrate v2 backups and drive factory and
hardware-in-the-loop qualification.

The release pipeline must produce:

- independently signed platform and runtime components;
- one signed paired release for ordinary installation;
- SBOM and provenance tied to a clean source revision;
- a factory image and one-time setup credential outside the public release;
- contract, compatibility and partition-budget reports; and
- machine-readable hardware qualification evidence.

Private signing keys, secure-boot keys, flash-encryption material and setup
passwords remain outside the repository and CI artifacts.

`qualification_runner.py` persists a release-bound campaign, monitors a JSON
health endpoint over server-authenticated or mutual TLS, and records explicit
controlled-test outcomes. A failed probe records network unavailability only;
it does not fabricate device-health or storage evidence. The command exits 0
only when every promotion gate passes and exits 2 while evidence is incomplete.
