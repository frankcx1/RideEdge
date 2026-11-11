"""Washington TNC minimum pay floors (RCW 49.46.300), 2026.

Eastside pickups (Kirkland / Bellevue / Redmond) use the statewide card
unless the trip is already inside Seattle. Starting in Seattle pays more.
"""

SEATTLE_PER_MILE = 1.63
SEATTLE_PER_MINUTE = 0.70
SEATTLE_TRIP_MINIMUM = 6.12
WASHINGTON_PER_MILE = 1.38
WASHINGTON_PER_MINUTE = 0.40
WASHINGTON_TRIP_MINIMUM = 3.55


def public() -> dict:
    return {
        "year": 2026,
        "effective_date": "2026-01-01",
        "source": "https://lni.wa.gov/workers-rights/industry-specific-requirements/transportation-network-company-drivers-rights/getting-paid",
        "seattle": {
            "per_mile": SEATTLE_PER_MILE,
            "per_minute": SEATTLE_PER_MINUTE,
            "trip_minimum": SEATTLE_TRIP_MINIMUM,
            "applies": "trips starting inside the City of Seattle, or the Seattle portion under L&I mixed-geography rules",
        },
        "washington": {
            "per_mile": WASHINGTON_PER_MILE,
            "per_minute": WASHINGTON_PER_MINUTE,
            "trip_minimum": WASHINGTON_TRIP_MINIMUM,
            "applies": "trips outside the City of Seattle across Washington State (Kirkland, Bellevue, Redmond, SEA curb, etc.)",
        },
        "note": (
            "Tips do not count toward the statutory floor. Standard non-shared trips starting outside Seattle "
            "generally accrue the statewide rate ($1.38/mi + $0.40/min, $3.55 min), whereas trips starting in Seattle "
            "or mixed-geography shared rides with a Seattle segment follow Washington L&I's geographic split rules."
        ),
    }
