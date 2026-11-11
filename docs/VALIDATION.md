# Sanitized export validation

Verified on Windows using Python 3.11, Node.js, JDK 17 and Android SDK 36.

| Check | Result |
|---|---|
| Python suite | 808 passed, 18 skipped |
| Android debug build | Successful |
| Android debug unit tests | 131 passed, no failures or skips |
| JavaScript UI suites | 51 passed |
| Secret scanning | Gitleaks plus comparison against private local credentials and location values; no publishable findings |

The Python skips are intentional: 15 depend on excluded private driving/replay fixtures, two on personal podcast narration, and one on a running local model. No fabricated observations were inserted to make those tests pass. Test policy files are isolated from directories used to assert that application code did not write private route data. The residential-origin regression uses an artificial test-only origin.

Python emitted two existing WebSocket deprecation warnings. Android emitted existing API/deprecation warnings; its build and tests passed. These checks do not certify a fresh hardware deployment, live provider access, model quality, or Android Auto acceptance in a particular vehicle.

## Reproduce

From the repository root, after installing the documented Python dependencies:

```powershell
$env:MOCK_FEEDS = '1'
$env:FAROL_GROK_IN_MOCK = '0'
$env:FAROL_LOCAL_MANAGE = 'external'
$env:FAROL_LOCAL_URL = 'http://127.0.0.1:1/v1/chat/completions'
python -m pytest -q -rs
node --test tests/ask-ui.test.cjs tests/location-ui.test.cjs tests/mobile-ui.test.cjs tests/podcast-ui.test.cjs tests/voice-ui.test.cjs
cd android
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug --console=plain
```

The deliberately unreachable model URL prevents a test from requesting live inference. These checks used mock feeds and did not restart the original backend, authorize paid-provider calls, or deploy an APK to a phone.
