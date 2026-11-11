package com.rideedge.app

import org.json.JSONObject
import java.time.Duration
import java.time.Instant

data class SeaTacFlight(val ident: String, val origin: String, val arrivalAt: Instant, val timeBasis: String, val timeField: String)
data class SeaTacHour(
    val startsAt: Instant, val endsAt: Instant, val fetchedAt: Instant?, val validUntil: Instant?,
    val windowMinutes: Double, val sampled: Int?, val estimated: Int?, val returned: Int?,
    val usable: Boolean, val mode: String, val coverage: String, val extrapolated: Boolean,
    val partialHour: Boolean, val longHaul: Int?, val estimateMethod: String,
    val readinessStart: Instant?, val readinessEnd: Instant?, val readinessBasis: String,
    val timingCounts: Map<String, Int>, val excluded: Map<String, Int>, val flights: List<SeaTacFlight>,
)
data class SeaTacReport(
    val serverTime: Instant, val fetchedAt: Instant?, val state: String, val hours: List<SeaTacHour>,
    val summary: String, val coverageNote: String, val timingNote: String,
    val attempts: Int?, val failures: Int?, val cacheHits: Int?, val refreshing: Boolean,
)

data class SeaTacReceipt(val report: SeaTacReport, val elapsedMs: Long, val bootId: Int) {
    fun serverNow(nowElapsed: Long, currentBootId: Int): Instant? =
        if (currentBootId != bootId || nowElapsed < elapsedMs) null else report.serverTime.plusMillis(nowElapsed-elapsedMs)

    fun remaining(nowElapsed: Long, currentBootId: Int): List<SeaTacHour> {
        val now = serverNow(nowElapsed, currentBootId) ?: return emptyList()
        return report.hours.filter { it.endsAt > now }
    }

    fun usable(hour: SeaTacHour, nowElapsed: Long, currentBootId: Int): Boolean {
        val now = serverNow(nowElapsed, currentBootId) ?: return false
        return hour.usable && hour.mode in setOf("live", "cache") && hour.estimated != null &&
            hour.fetchedAt != null && hour.validUntil != null && hour.endsAt > now && hour.validUntil > now &&
            Duration.between(hour.fetchedAt, now).seconds in -300..1799
    }

    fun peak(nowElapsed: Long, currentBootId: Int): SeaTacHour? = remaining(nowElapsed, currentBootId)
        .filter { usable(it, nowElapsed, currentBootId) && (it.estimated ?: 0) > 0 }
        .maxWithOrNull(compareBy<SeaTacHour> { it.estimated }.thenBy { it.longHaul ?: 0 }.thenByDescending { it.startsAt })
}

object SeaTacParser {
    fun parse(json: JSONObject): SeaTacReport {
        require(json.get("report_schema_version") == 1) { "SeaTac report needs a compatible backend" }
        fun JSONObject.time(key: String): Instant? = if (isNull(key)) null else Instant.parse(getString(key))
        fun JSONObject.count(key: String): Int? {
            if (isNull(key)) return null
            val value = get(key)
            require(value is Int || value is Long)
            val number = (value as Number).toLong()
            require(number in 0..Int.MAX_VALUE.toLong())
            return number.toInt()
        }
        fun JSONObject.counts(key: String): Map<String, Int> = optJSONObject(key)?.let { obj ->
            obj.keys().asSequence().associateWith { obj.count(it) ?: error("Missing count") }
        } ?: emptyMap()
        val rows = json.getJSONArray("hours")
        val hours = (0 until rows.length()).map { i ->
            val h = rows.getJSONObject(i)
            val start = h.time("starts_at") ?: error("Missing interval start")
            val end = h.time("ends_at") ?: error("Missing interval end")
            require(end > start && Duration.between(start, end).seconds <= 3600)
            val flights = h.optJSONArray("flights")
            SeaTacHour(start, end, h.time("fetched_at"), h.time("valid_until"),
                h.getDouble("window_minutes").also { require(it.isFinite() && it > 0 && it <= 60) },
                h.count("sampled_flights"), h.count("estimated_planes"), h.count("returned_records"),
                h.getBoolean("usable"), h.getString("mode"), h.getString("coverage"), h.getBoolean("extrapolated"),
                h.getBoolean("partial_hour"), h.count("long_haul_count"), h.optString("estimate_method"),
                h.time("passenger_ready_starts_at"), h.time("passenger_ready_ends_at"), h.optString("passenger_ready_basis"),
                h.counts("timing_basis_counts"), h.counts("excluded_records"),
                (0 until (flights?.length() ?: 0)).map { index -> flights!!.getJSONObject(index).let { f ->
                    SeaTacFlight(f.getString("ident"), f.getString("origin"), f.time("arrival_at") ?: error("Missing flight time"),
                        f.getString("time_basis"), f.getString("time_field"))
                } })
        }
        val usage = json.optJSONObject("provider_usage")
        return SeaTacReport(json.time("server_time") ?: error("Missing report clock"), json.time("fetched_at"),
            json.getString("state"), hours, json.optString("summary"), json.optString("coverage_note"), json.optString("timing_note"),
            usage?.count("http_attempts"), usage?.count("http_failures"), usage?.count("cache_hits"), json.optBoolean("refreshing"))
    }
}
