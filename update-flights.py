"""Fetch only this trip's flights. Key supplied by GitHub Actions secret, never published."""
import base64, datetime as dt, json, os, pathlib, urllib.parse, urllib.request
UTC=dt.timezone.utc
FLIGHTS=[('DL1147','DAL1147','ORD','ATL','2026-09-21T16:29:00Z','2026-09-21T18:30:00Z'),('DL210','DAL210','ATL','CPT','2026-09-22T01:00:00Z','2026-09-22T15:50:00Z'),('4Z326','LNK326','CPT','WDH','2026-09-24T08:40:00Z','2026-09-24T10:50:00Z'),('4Z327','LNK327','WDH','CPT','2026-10-04T11:40:00Z','2026-10-04T13:45:00Z'),('DL211','DAL211','CPT','ATL','2026-10-04T18:05:00Z','2026-10-05T10:25:00Z'),('DL1178','DAL1178','ATL','ORD','2026-10-05T11:25:00Z','2026-10-05T13:36:00Z')]
def parse(s): return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def iso(d): return d.isoformat().replace('+00:00','Z')
def match(f, spec):
    scheduled=f.get('scheduled_out') or f.get('scheduled_off')
    return scheduled and abs((parse(scheduled)-parse(spec[4])).total_seconds())<6*3600 and (f.get('origin') or {}).get('code_iata')==spec[2] and (f.get('destination') or {}).get('code_iata')==spec[3]
def status(f):
    if f.get('cancelled'): return 'cancelled'
    if f.get('diverted'): return 'diverted'
    if f.get('actual_in'): return 'arrived'
    if f.get('actual_on'): return 'landed'
    if f.get('actual_off'): return 'airborne'
    if f.get('actual_out'): return 'departed'
    return 'scheduled'
def run():
    key=os.environ.get('FLIGHTAWARE_API_KEY')
    if not key:
        print('Waiting for the FLIGHTAWARE_API_KEY repository secret.');return
    path=pathlib.Path('flight-data.json')
    data=json.loads(path.read_text()) if path.exists() else {'version':1,'flights':{},'estimatedUsageUsd':0}
    now=dt.datetime.now(UTC)
    # Conservative cumulative gross API budget for this trip, before monthly allowances.
    cap=15.0
    def get(endpoint, cost, **params):
        if data['estimatedUsageUsd']+cost>cap: raise RuntimeError('Trip API budget reached')
        data['estimatedUsageUsd']=round(data['estimatedUsageUsd']+cost,3)
        req=urllib.request.Request('https://aeroapi.flightaware.com/aeroapi/'+endpoint+'?'+urllib.parse.urlencode(params),headers={'x-apikey':key})
        with urllib.request.urlopen(req,timeout=25) as r: return json.load(r)
    for spec in FLIGHTS:
        name,ident,origin,dest,departure,arrival=spec
        old=data['flights'].get(name,{})
        if old.get('status') in ('arrived','cancelled'): continue
        end=max(parse(arrival),parse(old.get('estimated_in') or arrival))+dt.timedelta(hours=8)
        # Hard stop prevents a stale delay estimate keeping the job running indefinitely.
        end=min(end,parse(arrival)+dt.timedelta(hours=24))
        if not parse(departure)-dt.timedelta(hours=6)<=now<=end: continue
        if old.get('checkedAt') and (now-parse(old['checkedAt'])).total_seconds()<270: continue
        try:
            result=get('flights/'+ident,.005,ident_type='designator',start=iso(parse(departure)-dt.timedelta(hours=6)),end=iso(parse(departure)+dt.timedelta(hours=6)),max_pages=1)
            candidates=[f for f in result.get('flights',[]) if match(f,spec)]
            if not candidates: continue
            f=candidates[0];record={k:f.get(k) for k in ('scheduled_out','scheduled_in','estimated_out','estimated_in','actual_out','actual_off','actual_on','actual_in')}
            record.update(status=status(f),checkedAt=iso(now),position=old.get('position'),mapAt=old.get('mapAt'))
            data['flights'][name]=record
            if record['status'] in ('airborne','landed','arrived','diverted'):
                flight_id=urllib.parse.quote(f['fa_flight_id'],safe='')
                try: record['position']=get('flights/'+flight_id+'/position',.01).get('last_position')
                except Exception: print(name+': position unavailable; preserving prior report.')
                if not old.get('mapAt') or (now-parse(old['mapAt'])).total_seconds()>=900 or record['status']=='arrived':
                    try:
                        m=get('flights/'+flight_id+'/map',.03,width=1000,height=480,show_airports='true',airports_expand_view='true',show_data_block='true')
                        content=base64.b64decode(m['map'],validate=True)
                        if not content.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Unexpected map format')
                        pathlib.Path('flight-map-'+name+'.png').write_bytes(content);record['mapAt']=iso(now)
                    except Exception: print(name+': map unavailable; preserving prior map.')
        except Exception:
            # Do not log response content or request headers; preserve last successful data.
            print(name+': update unavailable or trip budget reached.')
    data['estimatedUsageUsd']=round(data['estimatedUsageUsd'],3)
    path.write_text(json.dumps(data,indent=2)+'\n')
if __name__=='__main__': run()
