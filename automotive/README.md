# Farol Automotive proof of concept

This is a minimal Android Automotive OS POI companion. It retrieves a paired,
short-lived navigation command from the Surface and, after an explicit driver
tap, launches built-in Google Maps with the official `google.navigation:`
intent.

It is intentionally a proof of concept:

- Published routes are `demo_only` zone centroids, not approved legal staging
  points.
- Driver confirmation is always required.
- Cleartext HTTP is allowed only for emulator hosts `10.0.2.2` and `127.0.0.1`.
- Release builds reject every car host until a production allowlist exists.
- Google and Volvo credentials, email addresses, and VINs are not needed or
  stored.

## Verified toolchain and result

The proof was built and exercised on this workstation on August 10, 2026 with
Java 17, Gradle 8.10.2, Android SDK 35, Car App Library 1.7.0, and the Android
35 Google Play Automotive emulator. The car host fetched the Surface command,
and Google Maps accepted its `google.navigation:` intent.

Volvo also publishes Volvo-flavored XC40 and EX30 emulator images. A Volvo
image is the next compatibility check before physical-car testing.

## Configure

1. Set `ANDROID_HOME` to the Android SDK.
2. Generate a long random pairing token.
3. Provide the same `FAROL_CAR_TOKEN` to the build and Surface process.
4. Set `FAROL_ENDPOINT` while building. With
   `adb reverse tcp:8787 tcp:8787`, use
   `http://127.0.0.1:8787/api/navigation/current`.

`local.properties` remains available as a developer-only fallback, but
environment variables avoid persisting pairing material in the project. The
file is ignored.

Example Surface session in PowerShell:

```powershell
$env:FAROL_CAR_TOKEN = "replace-with-a-generated-token"
python -m farol.api
```

## Exercise the contract

1. Open the Friday replay on the Surface.
2. Select a decision and press **PUBLISH VOLVO DEMO**.
3. Open Farol in the Automotive emulator.
4. Press **REFRESH** if necessary.
5. Confirm the card says `DEMO ROUTE - NOT DRIVER ADVICE`.
6. Press **NAVIGATE** and confirm built-in Google Maps receives the route.

## Before a real-car test

- Replace centroids with driver-approved legal `WAIT` anchors and bounded
  `ROAM` waypoints.
- Use TLS instead of cleartext LAN HTTP.
- Replace the embedded debug token with a proper short-lived pairing flow.
- Configure the release host certificate allowlist.
- Verify Volvo Google Play availability through an internal AAOS test track.
- Keep explicit confirmation; do not take over the vehicle display.
