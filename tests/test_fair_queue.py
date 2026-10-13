"""Fast unit: catalogue/first-pass fairness without capping repairs. Expected 1s, max 5s."""
import asyncio
from catalog_json.fair_queue import FairWorkQueue


def test_admission_rotates_catalogues_and_lanes_without_lost_obligations():
    async def run():
        q=FairWorkQueue(['small','innovations','armature']);serial=0
        def add(cat,lane):
            nonlocal serial
            serial+=1;q.put_nowait((lane,serial,{'id':cat}))
        add('small',0)
        for _ in range(10):add('innovations',1);add('armature',1)
        admitted=[]
        for _ in range(8):
            prefetched=await q.get();chosen=q.at_admission(prefetched)
            admitted.append((chosen[0],chosen[2]['id']));q.task_done()
            if chosen[0]==0:add('small',0)
        assert admitted[:4]==[(1,'innovations'),(0,'small'),(1,'armature'),(0,'small')]
        while not q.empty():q.get_nowait();q.task_done()
        await asyncio.wait_for(q.join(),.1)
    asyncio.run(run())


def test_prefetched_workers_do_not_pin_manifest_catalogue_at_admission():
    q=FairWorkQueue(['early','late'])
    for i in range(8):q.put_nowait((1,i,{'id':'early'}))
    q.put_nowait((1,8,{'id':'late'}))
    prefetched=[q.get_nowait() for _ in range(8)]
    assert q.at_admission(prefetched[0])[2]['id']=='early'
    assert q.at_admission(prefetched[1])[2]['id']=='late'
