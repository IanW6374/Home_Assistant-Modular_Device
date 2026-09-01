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
