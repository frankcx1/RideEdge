# Publication notes

This repository is a sanitized source snapshot of RideEdge, including the current uncommitted application work at export time. It has a new Git history; the original workstation's development commits were not published.

Included: backend, dashboard, Android phone/Android Auto code, legacy source modules, tests, public area catalogs, labeled fixtures, operations/editing helpers, and selected architecture documentation.

Excluded: `.env`, API/access keys and verifiers, signed packages and signing credentials, personal home coordinates, personal trip/earnings data, live provider caches, session notes and conversations, private model receipts, screenshots, recordings, captions, financial exports, and model weights. Personal machine identities were replaced with example configuration. The public starting point is illustrative.

Legacy replay source remains available for reference, but its private input files are omitted. Tests requiring those inputs explicitly skip when the data is absent. No synthetic records were substituted for real observations. The modern source fixtures retain their existing synthetic/provenance labels.

The public build's backend origin is configurable through `rideedgeOrigin`; the Python service uses `RIDEEDGE_PUBLIC_ORIGIN`. The example deployment uses externally managed local inference. The original running installation was not modified or restarted for publication.

Secret scanning supplements manual review; it cannot guarantee the absence of every possible sensitive value. Future changes should be reviewed with the same care. Do not add runtime directories or private captures with `git add -f`.
