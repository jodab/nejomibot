# Security

## Reporting a vulnerability

Report it privately, through
[GitHub's vulnerability reporting](https://github.com/jodab/nejomibot/security/advisories/new),
not in a public issue: what is affected, how to reproduce it, and the
version, which `/status` shows. Vulnerabilities in signal-cli-rest-api,
signal-cli or signalbot belong to those projects.

Only the latest release is supported. A fix comes as a new release:
published releases are never changed.

## Verifying a release

Each release is a signed tag. The repository's release workflow builds the
images from it, and attests their build provenance, signed through Sigstore
for the workflow's identity, without a key to keep:

```sh
gh attestation verify oci://docker.io/jodab/nejomibot:VERSION --repo jodab/nejomibot
gh attestation verify oci://ghcr.io/jodab/nejomibot:VERSION --repo jodab/nejomibot
```

Each shows the workflow that built the image, and the commit. Releases are
immutable from 0.99.36 on: their tags can't move, and GitHub signs an
attestation of each. The tag's own signature is checked with the key GitHub
has for its author:

```sh
gh release verify vVERSION
curl -fsS https://github.com/jodab.gpg | gpg --import
git verify-tag vVERSION
```
