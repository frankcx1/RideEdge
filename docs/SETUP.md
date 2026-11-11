# Deployment setup

## Backend and authentication

Copy `.env.example` to `.env` and install the Python extras in the README. Start with `MOCK_FEEDS=1`. Generate your own key using `python -m farol.access issue`; the verifier is saved under the ignored `.cache/` directory. Do not paste keys into source, screenshots, issues, URLs, or GitHub.

The API's access middleware expects a configured HTTPS origin. Set `RIDEEDGE_PUBLIC_ORIGIN=https://your-host.example.com`. The example hostname is deliberately nonfunctional. Put the loopback service behind your own TLS reverse proxy or private-network HTTPS endpoint. Configure the proxy to preserve the public Host and forward the HTTPS scheme; only a loopback proxy is trusted for TLS termination. Do not bypass the middleware or expose an unauthenticated public service.

For the Android build, supply `-PrideedgeOrigin=https://your-host.example.com`; it must match the backend's public origin. Access keys are entered at runtime and encrypted with Android Keystore. Do not set an API key in a Gradle property.

## Local model

`FAROL_LOCAL_MANAGE=external` uses an already running loopback model server without stopping, loading, or leasing another application's GPU. Configure `FAROL_LOCAL_MODEL` to match `/v1/models` exactly. The Qwen path checks the model family and validates structured responses. No model weights are redistributed here.

`beast/` contains optional Windows operations scripts from the original deployment. Paths in those scripts are examples and require adaptation. The separate `C:/ProgramData/gpu-lease` coordinator, model downloads, and other applications are not included. Do not run those scripts as a substitute for configuring your own deployment.

## Provider costs and local storage

Provider keys remain on the backend in `.env`. Start with mock feeds; only set `MOCK_FEEDS=0` once providers, budgets, and retention are configured. BestTime uses a separate allowance policy and cached results. Keep caches, database files, logs, receipts, `.env`, signing material, and device captures out of Git.

The published area catalog uses an illustrative public location. It is not a residence or a trip observation. Public place pins are geographic references, not promises that pickup or parking is permitted.

## Android Auto and media tools

The current Android app includes the projected Android Auto service. Install/build using your own package and signing/distribution setup as appropriate. Head-unit acceptance and driving restrictions are controlled by Android Auto; do not bypass its safety requirements. The optional preview build uses explicitly labeled fixtures and is distinct from live guidance.

Scripts under `scripts/media/` are editing helpers. Their input recordings and personal narration are intentionally omitted; provide your own media and update paths before using them. They are not needed to run the app.
