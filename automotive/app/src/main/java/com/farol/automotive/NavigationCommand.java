package com.farol.automotive;

import java.time.Instant;
import org.json.JSONObject;

final class NavigationCommand {
    final String id;
    final String action;
    final String label;
    final double latitude;
    final double longitude;
    final boolean demoOnly;
    final boolean confirmationRequired;
    final String expiresAt;
    final long expiresAtEpochMs;

    NavigationCommand(JSONObject json) {
        JSONObject destination = json.optJSONObject("destination");
        if (destination == null) throw new IllegalArgumentException("destination is required");
        id = json.optString("command_id", "unknown");
        action = json.optString("action", "MOVE");
        label = destination.optString("label", "Farol destination");
        latitude = destination.optDouble("latitude");
        longitude = destination.optDouble("longitude");
        demoOnly = json.optBoolean("demo_only", true);
        confirmationRequired = json.optBoolean("driver_confirmation_required", true);
        expiresAt = json.optString("expires_at", "");
        long parsedMs = 0L;
        if (!expiresAt.isEmpty()) {
            try {
                parsedMs = Instant.parse(expiresAt).toEpochMilli();
            } catch (Exception ignored) {
                parsedMs = 0L;
            }
        }
        expiresAtEpochMs = parsedMs;
    }

    boolean isExpired() {
        return expiresAtEpochMs <= 0L || System.currentTimeMillis() >= expiresAtEpochMs;
    }

    String navigationUri() {
        return "google.navigation:q=" + latitude + "," + longitude;
    }
}
