# Optional Windows operations scripts

These scripts document the original workstation deployment. They are optional, require local adaptation, and are not a portable one-command installer.

For a new installation, follow [Setup](../docs/SETUP.md), run the backend directly, and use `FAROL_LOCAL_MANAGE=external` with your own loopback Qwen server.

- `farol-server.ps1`: process identity checks and optional scheduled-task/reverse-proxy management.
- `farol-shift.ps1`, `farol-recover.ps1`: integration with an external GPU lease coordinator and optional companion application.
- `runtime-safety.ps1`, `server-safety.ps1`: process-identity checks used by those integrations.
- `local-models.json`: example model/server paths; install weights separately and configure paths and served aliases.
- `event-calendar.ps1`: optional public-event collector with a separately configured output directory.
- `farol-speech.ps1`: optional Windows speech support.

The `C:/ProgramData/gpu-lease` coordinator and companion application are not distributed here. Example paths, model names, and hostnames must be configured before these scripts are used. Do not run model handback scripts against an unrelated workload.

Keep remote access behind your own HTTPS/private-network setup. The current access middleware requires its configured secure origin. Never place an access key or provider key in a URL.
