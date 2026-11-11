package com.rideedge.app

import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

/** Single authenticated HTTPS attempt. No redirects or retry of sent mutations. */
internal class RideEdgeHttpTransport(
    private val open: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
) {
    fun request(path: String, method: String, body: JSONObject?, timeoutMs: Int, key: String): JSONObject {
        require(RideEdgeConnection.validKey(key))
        val conn = open(URL(RideEdgeConnection.url(path))).apply {
            requestMethod = method
            instanceFollowRedirects = false
            connectTimeout = 4000
            readTimeout = timeoutMs
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Authorization", "Bearer $key")
            body?.optString("idempotency_key")?.takeIf { it.isNotBlank() }?.let {
                setRequestProperty("X-Idempotency-Key", it)
            }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null) OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
            val code = conn.responseCode
            if (code == 401 || code == 403) throw AccessRequiredException("The access key was rejected. Open Connection to reconnect.")
            if (code == 503) {
                // Read only a bounded error code, never display provider/server echoes.
                val detail = conn.errorStream?.bufferedReader(Charsets.UTF_8)?.use { reader ->
                    val chars = CharArray(1024)
                    val size = reader.read(chars)
                    if (size > 0) runCatching { JSONObject(String(chars, 0, size)).optString("code") }.getOrNull() else null
                }
                if (detail == "setup_required") throw AccessRequiredException("workstation needs an access key. Create one there, then reconnect.")
            }
            if (code !in 200..299) throw IllegalStateException("RideEdge request failed (HTTP $code).")
            val text = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } catch (error: AccessRequiredException) { throw error }
        catch (error: IllegalStateException) { throw error }
        catch (_: Exception) { throw IllegalStateException("Service connection unavailable. Check Tailscale and workstation.") }
        finally { conn.disconnect() }
    }
}
