"use strict";

// First release: explicit read-only commands, not conversational constraint parsing.
function voiceIntent(raw) {
  const text = String(raw || "").trim();
  const normalized = text.toLowerCase().replace(/[.,!?]/g, "").replace(/[’]/g, "'").trim();
  if (/^(stop|cancel|stop talking|be quiet)$/.test(normalized)) return {kind:"stop"};
  if (/^(read (my |the )?recommendation|repeat( that)?|say that again)$/.test(normalized)) return {kind:"read"};
  if (/^(should i drive( tonight)?|read (me )?(my |the )?(tonight )?brief)$/.test(normalized)) return {kind:"brief"};
  if (/^(where should i go|where do i go|what should i do)( next| now)?$/.test(normalized)) return {kind:"here"};
  if (/^(what's around me|what is around me|show (me )?(what's )?nearby|around me)$/.test(normalized)) return {kind:"nearby"};
  // Never silently discard a budget, preference, comparison, or navigation request.
  if (/\b(under|over|less|more|minutes?|hours?|avoid|prefer|compare|versus|vs|finish|budget|dollars?|limit|navigate|send|take me|directions|earn|surge)\b|\$/.test(normalized)) return {kind:"unsupported"};
  const place = text.replace(/\b(where should i go|where do i go|what should i do)[\s?!.,]*$/i, "")
    .replace(/^(i['’]?m|i am|we are|we['’]?re)\s+(at|in|near)\s+/i, "")
    .replace(/^(check|near)\s+/i, "").replace(/[.?!,\s]+$/, "").trim();
  if (!place || place.length > 100 || /\b(and then|or|should|could|would|why|how)\b/i.test(place)) return {kind:"unsupported"};
  return {kind:"location", place};
}

function createVoice(handlers, env = window) {
  const doc = env.document, byId = (id) => doc.getElementById(id);
  const playbackLabel = (label) => { byId("voice-play").textContent = label; byId("brief-listen").textContent = label === "Listen" ? "Listen to brief" : label; };
  let serial = 0, recorder = null, stream = null, timer = null, ticker = null;
  let controller = null, audio = null, audioUrl = null, pendingPlay = false, recording = false;
  const message = (text) => { byId("voice-status").textContent = text; byId("voice-global-status").textContent = text; byId("voice-global-status").classList.toggle("hidden", !text); };
  function tracksOff() { if (stream) stream.getTracks().forEach((track) => track.stop()); stream = null; }
  function stopAudio() {
    if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); }
    audio = null; pendingPlay = false;
    if (audioUrl) env.URL.revokeObjectURL(audioUrl);
    audioUrl = null; playbackLabel("Listen");
  }
  function cancel(clear = true) {
    serial++; if (controller) controller.abort(); controller = null;
    env.clearTimeout(timer); env.clearInterval(ticker);
    if (recorder && recorder.state !== "inactive") recorder.stop();
    recorder = null; recording = false; tracksOff(); stopAudio();
    byId("voice-record").textContent = "Speak"; byId("voice-record").disabled = false;
    byId("voice-cancel").classList.add("hidden");
    if (clear) message("");
  }
  async function readBody(response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Voice is unavailable. Try typing instead.");
    return body;
  }
  async function speak(text, token = serial) {
    if (!text || token !== serial) return;
    stopAudio(); message("Preparing spoken reply…");
    byId("voice-cancel").classList.remove("hidden");
    controller = new env.AbortController();
    const response = await env.fetch("/api/voice/speak", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({text:text.slice(0, 700)}), signal:controller.signal});
    if (!response.ok) await readBody(response);
    const blob = await response.blob();
    if (token !== serial) return;
    audioUrl = env.URL.createObjectURL(blob); audio = new env.Audio(audioUrl);
    audio.onended = () => { if (token === serial) { stopAudio(); message(""); byId("voice-cancel").classList.add("hidden"); } };
    audio.onerror = () => { if (token === serial) { stopAudio(); message("Couldn’t play the reply. The answer is still on screen."); } };
    try { await audio.play(); if (token === serial) { playbackLabel("Stop speaking"); message("Speaking…"); } }
    catch { if (token === serial) { pendingPlay = true; playbackLabel("Play reply"); message("Tap Play reply to hear the answer."); } }
  }
  async function execute(text, token = serial) {
    const intent = voiceIntent(text), current = () => token === serial;
    if (intent.kind === "stop") { cancel(); return; }
    if (handlers.wantsQuestion?.()) {
      message("Qwen is checking your question…");
      const answer = await handlers.question(text, current);
      if (current() && answer) await speak(answer, token);
      else if (current()) message("Check Ask RideEdge for the question status.");
      return;
    }
    if (intent.kind === "unsupported") { message("For now, say a location, ‘where should I go’, or ‘read my brief’. Preferences and comparisons aren’t voice commands yet."); return; }
    if (intent.kind === "nearby") { handlers.nearby(); return; }
    if (intent.kind === "location" || intent.kind === "here") {
      message("Checking the area…");
      const ok = await handlers.location(intent.place, current);
      if (!current()) return;
      if (!ok) { message("Choose or check a location first. You can edit what I heard below."); return; }
    }
    if (current()) await speak(handlers.answer(intent.kind === "brief"), token);
  }
  async function listen(forceBrief = false) {
    if (audio && !audio.paused) { cancel(); return; }
    if (pendingPlay && audio) {
      try { await audio.play(); pendingPlay = false; playbackLabel("Stop speaking"); message("Speaking…"); } catch { message("Playback is blocked. Check this browser’s sound permission."); }
      return;
    }
    cancel(); const token = serial;
    try { await speak(handlers.answer(forceBrief), token); }
    catch (error) { if (token === serial && error.name !== "AbortError") message(error.message); }
  }
  function finish() {
    env.clearTimeout(timer); env.clearInterval(ticker);
    if (recorder && recorder.state !== "inactive") recorder.stop();
    tracksOff(); recording = false;
  }
  async function record() {
    if (recording) { finish(); return; }
    cancel(); const token = serial;
    try {
      if (!env.isSecureContext) throw new Error("Microphone needs the secure HTTPS link in Preferences. Typed input still works here.");
      if (!env.navigator.mediaDevices?.getUserMedia || !env.MediaRecorder) throw new Error("Recording is unavailable in this browser. Open the secure link in Chrome.");
      message("Allow the microphone to speak a location."); byId("voice-record").disabled = true;
      byId("voice-cancel").classList.remove("hidden");
      const acquired = await env.navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true, noiseSuppression:true}, video:false});
      if (token !== serial) { acquired.getTracks().forEach((track) => track.stop()); return; }
      stream = acquired;
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"].find((type) => env.MediaRecorder.isTypeSupported(type));
      recorder = new env.MediaRecorder(stream, {...(mime ? {mimeType:mime} : {}), audioBitsPerSecond:32000});
      const captured = recorder, chunks = []; let size = 0;
      recorder.ondataavailable = (event) => {
        if (token !== serial) return;
        size += event.data.size;
        if (size > 2 * 1024 * 1024) { cancel(false); message("Recording was too large. Try a shorter phrase."); return; }
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => { if (token === serial) { cancel(false); message("Recording stopped unexpectedly. Please try again."); } };
      recorder.onstop = async () => {
        if (token !== serial) return;
        tracksOff(); env.clearTimeout(timer); env.clearInterval(ticker); recording = false;
        byId("voice-record").textContent = "Transcribing…"; byId("voice-record").disabled = true; message("Transcribing…");
        controller = new env.AbortController();
        try {
          const blob = new env.Blob(chunks, {type:captured.mimeType || mime || "audio/webm"});
          const result = await readBody(await env.fetch("/api/voice/transcribe", {method:"POST", headers:{"Content-Type":blob.type}, body:blob, signal:controller.signal}));
          if (token !== serial) return;
          byId("voice-transcript").value = result.text; byId("voice-heard").textContent = `Heard: ${result.text}`;
          byId("voice-transcript-panel").classList.remove("hidden");
          byId("voice-record").textContent = "Speak"; byId("voice-record").disabled = false;
          await execute(result.text, token);
        } catch (error) { if (token === serial && error.name !== "AbortError") message(error.message); }
        finally { if (token === serial) { byId("voice-record").textContent = "Speak"; byId("voice-record").disabled = false; } }
      };
      recorder.start(1000); recording = true; byId("voice-record").disabled = false; byId("voice-record").textContent = "Finish";
      const began = Date.now(); message("Listening… tap Finish when done.");
      ticker = env.setInterval(() => message(`Listening… ${Math.floor((Date.now() - began) / 1000)}s / 20s`), 1000);
      timer = env.setTimeout(finish, 20000);
    } catch (error) {
      if (token !== serial) return;
      cancel(false);
      message(error.name === "NotAllowedError" ? "Microphone permission was denied. Allow it in Chrome’s site settings, or type a location." : error.message);
    }
  }
  byId("voice-record").addEventListener("click", record);
  byId("voice-play").addEventListener("click", () => listen());
  byId("brief-listen").addEventListener("click", () => listen(true));
  byId("voice-cancel").addEventListener("click", () => cancel());
  byId("voice-use").addEventListener("click", async () => { cancel(); const token = serial; try { await execute(byId("voice-transcript").value, token); } catch (error) { if (token === serial) message(error.message); } });
  doc.addEventListener("visibilitychange", () => { if (doc.hidden) cancel(); });
  env.addEventListener("pagehide", () => cancel());
  return {cancel, record, listen};
}
if (typeof module !== "undefined") module.exports = {voiceIntent, createVoice};
if (typeof window !== "undefined") window.createFarolVoice = createVoice;
