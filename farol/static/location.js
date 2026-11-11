"use strict";

// Shared by Working and Around you. One explicit device reading, held only in
// page memory; no server/IP geolocation fallback or continuous tracking.
const RideEdgeLocation = (() => {
  const MAX_FIX_AGE = 30000, MAX_USE_AGE = 5 * 60000, MAX_ACCURACY = 1000;
  function validate(position, now = Date.now()) {
    const {latitude, longitude, accuracy} = position?.coords || {}, timestamp = position?.timestamp;
    if (![latitude, longitude, accuracy, timestamp].every(Number.isFinite)
        || accuracy < 0 || latitude < 47 || latitude > 48.2 || longitude < -123 || longitude > -121.5) {
      throw new Error("The device returned an unusable location. Choose an area or try again.");
    }
    if (now - timestamp > MAX_FIX_AGE || timestamp > now + 10000) {
      throw new Error("The device returned an old location. Tap location again for a fresh reading.");
    }
    if (accuracy > MAX_ACCURACY) {
      throw new Error("Location is too approximate. Allow precise location for this site and Chrome, or choose an area.");
    }
    return {latitude, longitude, accuracy, timestamp};
  }
  function get(env = window) {
    if (!env.isSecureContext) return Promise.reject(new Error("Device location needs HTTPS. Open the secure link or choose an area."));
    if (!env.navigator.geolocation) return Promise.reject(new Error("Device location is unavailable. Choose an area instead."));
    return new Promise((resolve, reject) => env.navigator.geolocation.getCurrentPosition(
      position => { try { resolve(validate(position)); } catch (error) { reject(error); } },
      error => reject(new Error(({1:"Location permission is blocked. Allow location for this site and Chrome, then retry.",
        2:"The device could not determine your location. Try again or choose an area.",
        3:"Location timed out. Try again with a clearer signal or choose an area."})[error.code] || "Could not read your device location.")),
      {enableHighAccuracy:true, timeout:15000, maximumAge:0}
    ));
  }
  function fresh(fix, now = Date.now()) { return Boolean(fix && now - fix.timestamp <= MAX_USE_AGE && fix.timestamp <= now + 10000); }
  function note(fix) {
    const at = new Date(fix.timestamp).toLocaleTimeString("en-US", {timeZone:"America/Los_Angeles", hour:"numeric", minute:"2-digit"});
    return `Device location · ±${Math.max(1, Math.round(fix.accuracy))} m · checked ${at}`;
  }
  function body(fix) { return {latitude:fix.latitude, longitude:fix.longitude}; }
  return {get, validate, fresh, note, body};
})();
if (typeof window !== "undefined") window.RideEdgeLocation = RideEdgeLocation;
if (typeof module !== "undefined") module.exports = RideEdgeLocation;
