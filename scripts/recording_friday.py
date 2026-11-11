"""Prepared Friday journey. Geography is real; readings and ride outcomes are authored.

No provider/model calls, no Uber dispatch integration, no production scoring.
Public area references replace the driver's private home and exact pickup points.
"""
import copy
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures/contracts"
BASE = datetime.fromisoformat("2026-11-07T00:00:00+00:00")  # Friday Nov 6, 4 PM PST
AREAS = {
    "home": ("Kirkland · shift start",47.665,-122.188),
    "kirkland": ("Downtown Kirkland",47.6769,-122.206),
    "totem": ("Totem Lake",47.711,-122.179),
    "redmond": ("Downtown Redmond",47.674,-122.1215),
    "bellevue": ("Downtown Bellevue",47.615,-122.201),
    "sea": ("SeaTac · airport drop-off",47.4435,-122.302),
    "southcenter": ("Southcenter · nearby fallback",47.459,-122.258),
    "seatac_hotels": ("SeaTac hotel corridor",47.434,-122.296),
    "des_moines": ("Downtown Des Moines",47.399,-122.327),
    "downtown": ("Downtown Seattle · hotel district",47.610,-122.334),
    "slu": ("South Lake Union dining",47.621,-122.337),
    "belltown": ("Belltown dining district",47.613,-122.345),
    "paramount": ("Paramount Theatre district",47.6133,-122.3314),
    "moore": ("Moore Theatre · Belltown",47.6117,-122.3421),
    "pioneer": ("Pioneer Square",47.6015,-122.333),
    "wamu": ("WAMU Theater district",47.595,-122.331),
    "capitol_hill": ("Capitol Hill · Pike/Pine",47.614,-122.319),
}
# offset, origin, choices, minutes, title, short label, explanation, story, evidence
STAGES = [
    (0,"home",["bellevue","kirkland","totem","redmond","belltown"],[20,8,13,15,35],
     "Friday begins in Kirkland","4 PM · Kirkland",
     "Bellevue combines hotels, offices and dinner activity within reach. Compare that cluster with staying in Kirkland.",
     "It is 4 PM at a public starting point in Kirkland. We head toward Bellevue for dinner-bound and airport-bound travelers.",
     "Bellevue hotel and office activity overlaps early dinner departures toward Seattle."),
    (75,"sea",["southcenter","seatac_hotels","des_moines","downtown"],[12,6,14,40],
     "The airport leg","5:15 PM · SeaTac",
     "After the airport drop-off, Southcenter is a nearby fallback if no rematch arrives. Follow an assigned rematch through Uber.",
     "At 4:30 PM, a Bellevue rider requests SeaTac. After the drop-off, a rematch takes us into Seattle in this shift story.",
     "Airport arrivals provide context. They do not reveal the queue, a rider's destination or whether a rematch will be offered."),
    (135,"downtown",["slu","belltown","paramount","pioneer","bellevue"],[8,6,5,8,30],
     "A Seattle drop-off changes the plan","6:15 PM · Seattle",
     "From the Seattle drop-off, South Lake Union offers a nearby dinner and hotel cluster. Rebuild the outlook around this starting area.",
     "The rematch ends in downtown Seattle. The next positioning decision starts here, rather than following the old Bellevue plan.",
     "Restaurant openings and hotel activity support the early-evening dining corridor."),
    (240,"slu",["belltown","capitol_hill","paramount","pioneer","bellevue"],[6,12,7,13,28],
     "Dinner departures","8 PM · Dinner",
     "Belltown's dining cluster is a short trip away as dinner departures build. Keep the theater window in the plan rather than arriving too early.",
     "After early-evening rides, we compare dinner departures in Belltown with the later theater and concert windows.",
     "Venue activity and hours support the dinner departure window; the next theater release is later."),
    (330,"belltown",["paramount","moore","capitol_hill","pioneer","bellevue"],[7,4,11,10,26],
     "Theater lets out","9:30 PM · Theater",
     "The Paramount-area exit window is approaching and the estimated trip is short. Compare the Moore and Capitol Hill before repositioning.",
     "The focus shifts from dinner to a theater release. In this prepared evening, the Paramount window is 9:40–10:10 PM.",
     "Paramount exit window: 9:40–10:10 PM. Travel and access can matter more than the largest crowd."),
    (390,"pioneer",["wamu","pioneer","capitol_hill","belltown","kirkland"],[8,3,16,13,30],
     "WAMU exit window","10:30 PM · WAMU",
     "The WAMU exit window overlaps a short trip from Pioneer Square. Consider pickup access and reassess if congestion rises.",
     "A later drop-off leaves us near Pioneer Square. The next window is WAMU, with a prepared exit period of 10:45–11:15 PM.",
     "WAMU exit window: 10:45–11:15 PM. Road access and traffic constrain the useful opportunity."),
    (480,"pioneer",["capitol_hill","belltown","downtown","slu","kirkland"],[12,10,7,13,27],
     "Capitol Hill after midnight","Midnight · Capitol Hill",
     "The concert release has passed. Capitol Hill's late-opening venues offer a broader nightlife cluster, while Belltown remains an alternative.",
     "We move on from the event and work Capitol Hill. Eastside closing activity stays in view if a ride takes us back across the lake.",
     "Late-opening Pike/Pine venues support a nightlife cluster beyond a single event."),
    (560,"home",["kirkland","redmond","totem","bellevue","capitol_hill"],[7,14,12,17,25],
     "The final Eastside window","1:20 AM · Eastside",
     "A return trip has brought us to Kirkland. Its downtown venues are closest; compare Redmond's activity before spending more time repositioning.",
     "An Eastside-bound ride brings us back. We compare Kirkland and Redmond around closing time, then wind down toward the 3 AM shift end.",
     "Closing-time activity, the present drop-off and travel determine which Eastside option still makes sense."),
]


def iso(value):
    return value.isoformat().replace("+00:00","Z")


def distance(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(*a,*b))
    return 3958.8*2*math.asin(math.sqrt(math.sin((lat2-lat1)/2)**2+
        math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2))


def plan_area(offset):
    for limit,key in [(120,"bellevue"),(210,"slu"),(315,"belltown"),(375,"paramount"),
                      (435,"wamu"),(555,"capitol_hill"),(615,"kirkland"),(660,"redmond")]:
        if offset<limit: return key
    return None


def build():
    from farol.collect import FEED_CATALOG
    base=json.loads((FIX/"radar-v1.json").read_text(encoding="utf-8"))
    airport=json.loads((FIX/"seatac-v1.json").read_text(encoding="utf-8"))
    roles={"besttime_busyness":"Relative venue activity; not a rider count",
           "google_places_closing":"Opening hours, venue identity and activity clusters",
           "google_routes_traffic":"Travel feasibility from the current drop-off",
           "ticketmaster_events":"Theater and concert schedules and exit windows",
           "flightaware_sea":"Hourly arrivals and passenger-readiness context",
           "nws_hourly":"Weather context across the rolling plan",
           "wsdot_traffic":"Road restrictions and disruption context"}
    scenes=[]
    for step,(offset,origin_key,keys,minutes,title,short,reason,story,evidence) in enumerate(STAGES):
        stamp=BASE+timedelta(minutes=offset)
        now,end=iso(stamp),iso(stamp+timedelta(hours=6))
        origin=AREAS[origin_key]
        travel=dict(zip(keys,minutes))

        def place(key,from_coords=None,future=False):
            name,lat,lon=AREAS[key]
            radius=distance(from_coords or origin[1:],(lat,lon))
            mins=round(4+radius*2.7) if future else travel.get(key,round(4+radius*2.7))
            event=key in {"paramount","moore","wamu"}
            p=copy.deepcopy(base["now"][0])
            p.update(id=f"demo:{key}",name=name,zone=key,latitude=lat,longitude=lon,
                radius_miles=round(radius,2),within_now_radius=radius<=5,
                route=dict(minutes=mins,miles=round(radius*1.35,1),basis="estimated",fetched_at=now),
                category="Events" if event else "Places",strength="Activity outlook",
                qwen_reason=reason if key==keys[0] and not future else "Compare this activity cluster with the selected area, timing and extra travel.",
                maps_url=f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
                navigation_note="Public area reference. Use the Maps handoff demo for navigation.",
                busyness=(78 if key==keys[0] else 62) if not event else None,
                busyness_basis="Venue-relative activity" if not event else None,
                valid_until=end,ends_at=end,actionable=not future,reachable=True,context_only=False,unavailable_reason=None)
            p["evidence"]=[dict(id=f"demo:{step}:{key}",source="Event schedule" if event else "Venue activity and hours",
                basis="replay",text=evidence if key==keys[0] else "Activity and timing alternative in this area.",
                fetched_at=now,measurement_time=now,starts_at=now,ends_at=end,value=None,
                timing_note="Prepared Friday scenario",role="opportunity",arrival_relevant=True)]
            return p

        places=[place(key) for key in keys]
        near=[p for p in places if p["within_now_radius"]]
        far=[p for p in places if not p["within_now_radius"] and p["radius_miles"]<=20]
        assert near and near[0]["id"]==f"demo:{keys[0]}"
        radar=copy.deepcopy(base)
        radar.update(snapshot_id=f"recording-{step}",source_snapshot_id=f"recording-sources-{step}",
            decision_revision=f"recording-{step}",generated_at=now,server_time=now,valid_until=end,
            next_refresh_at=iso(stamp+timedelta(minutes=15)),now=near,nearby=places,further=far,
            qwen={"state":"demo","detail":"Prepared review for this replay","code":None},
            scheduler={"state":"preview","next_review_at":None},comparison="Plan comparison for this replay.",
            limits="Reassess after each trip. Activity signals do not guarantee a rider.")
        radar["origin"].update(label=origin[0],zone=origin_key,mode="selected_area",latitude=origin[1],longitude=origin[2],fix_at=None)
        if step == 7:
            radar["origin"]["label"] = "Kirkland · return trip"
        plan=[]
        previous=origin[1:]
        for hour in range(6):
            key=keys[0] if hour==0 else plan_area(offset+hour*60)
            alt="belltown" if key!="belltown" else "capitol_hill"
            if key in {"kirkland","redmond","bellevue"}: alt="redmond" if key!="redmond" else "kirkland"
            options=[place(k,previous,True) for k in [key,alt]] if key else []
            if key:
                previous=AREAS[key][1:]
                for p in options:
                    p.update(qwen_reason="Recheck activity, actual drop-off and travel as this window approaches.",valid_until=None)
                    if offset+hour*60+60>660:
                        p.update(ends_at=iso(BASE+timedelta(minutes=660)),
                                 qwen_reason="Wind down this area and finish the shift by 3 AM.")
            plan.append(dict(starts_at=iso(stamp+timedelta(hours=hour)),ends_at=iso(stamp+timedelta(hours=hour+1)),
                selected_id=options[0]["id"] if options else None,options=options,
                selection_basis=("Wind down by 3 AM" if offset+hour*60+60>660 else "Activity and travel outlook") if key else "Shift ends at 3 AM",
                repeat_area=bool(plan and options and plan[-1]["selected_id"]==options[0]["id"]),
                outlook_note=("Finish by 3 AM within this window." if offset+hour*60+60>660 else "Reassess after the actual drop-off; future areas are conditional.") if key else "No positioning suggested after the planned shift end."))
        radar["plan"]=plan
        radar["algorithm_plan"]=copy.deepcopy(plan)
        if step in {0,4,5,7}: radar["algorithm_plan"][0]["selected_id"]=plan[0]["options"][1]["id"]
        feeds=[]
        for key,(label,cat) in FEED_CATALOG.items():
            used=key in roles
            feeds.append(dict(adapter=key,label=label,category=cat,mode="demo" if used else "not_used",
                healthy=used,enabled=used,stoplight="green" if used else "amber",signal_count=3 if used else 0,
                count_unit="records",fetched_at=now if used else None,age_minutes=0 if used else None,
                detail=roles.get(key,"Outside this scene's coverage"),plain_summary=roles.get(key,"No evidence supplied in this scene")))
        radar["feeds"]=[{k:f[k] for k in ["adapter","mode","signal_count","fetched_at"]} for f in feeds]
        health=dict(synthetic=True,total_count=len(feeds),enabled_count=7,healthy_count=7,collected_at=now,feeds=feeds,
            service_health_note="Source coverage and freshness for the selected scene.",
            radar_participation={"state":"demo","snapshot_id":radar["snapshot_id"],"sources":[],
                                "note":"Source roles in this replay. Availability and decision use are different."})
        air=copy.deepcopy(airport)
        counts=[14,18,16,12,9,6] if step<=2 else [9,12,14,10,7,4]
        peak=counts.index(max(counts))
        air.update(server_time=now,fetched_at=now,valid_until=end,expired=False,state="ready",best_hour_label=f"Hour {peak+1}",
            best_hour_starts_at=iso(stamp+timedelta(hours=peak)),best_lot_arrival_time=iso(stamp+timedelta(hours=peak,minutes=20)),
            summary="Arrival outlook. Airport queue and rematch probability are unknown.",timing_note="Estimated 20-minute passenger readiness delay.",
            provider_usage={"http_attempts":0,"http_failures":0,"cache_hits":0})
        for idx,(h,count) in enumerate(zip(air["hours"],counts)):
            start=stamp+timedelta(hours=idx)
            h.update(starts_at=iso(start),ends_at=iso(start+timedelta(hours=1)),hour_label=f"Hour {idx+1}",fetched_at=now,valid_until=end,
                estimated_planes=count,sampled_flights=count,returned_records=count,window_minutes=60,partial_hour=False,
                coverage="replay",mode="cache",usable=True,extrapolated=False,page_full=False,is_peak=idx==peak,
                estimate_method="Arrival count in the prepared scenario.",lot_arrival_target=iso(start+timedelta(minutes=20)),
                sample_flights=[f"DEMO{idx}{j:02} (demo)" for j in range(min(count,3))],
                passenger_ready_starts_at=iso(start+timedelta(minutes=20)),passenger_ready_ends_at=iso(start+timedelta(minutes=80)),
                passenger_ready_basis="Estimated 20-minute delay",timing_basis_counts={"scheduled_gate":count},
                flights=[dict(ident=f"DEMO{idx}{j:02}",origin="SEA demo",arrival_at=iso(start+timedelta(minutes=j*60/count)),
                              time_basis="scheduled_gate",time_field="scheduled_in",long_haul=False) for j in range(count)],long_haul_count=0)
        scenes.append(dict(id=step,title=title,short_title=short,description=reason,story=story,radar=radar,health=health,seatac=air,
            status={"synthetic":True,"backend":"demo","collector":{"running":False},"qwen_loaded":False,
                    "model_server_reachable":False,"qwen":{"state":"demo replay"},"evidence_generated_at":now}))
    payload={"schema_version":1,"synthetic":True,"title":"RideEdge Friday Shift",
        "provenance":{"kind":"synthetic","explanations":"scripted","live_inference":False,
                      "rides":"Authored story beats; no Uber dispatch integration",
                      "event_times":"Prepared windows, not verified event listings for November 6"},"stages":scenes}
    (FIX/"recording-demo.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n")
