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


def test_fresh_repair_precedes_backlog_without_starving_first_or_old_repairs():
    q=FairWorkQueue(['cat'])
    for i in range(40):q.put_nowait((0,i,{'id':'cat','page':i}))
    for i in range(40,80):q.put_nowait((1,i,{'id':'cat','page':i}))
    q.put_nowait((2,80,{'id':'cat','page':80}))
    admitted=[]
    for _ in range(4):
        task=q.at_admission(q.get_nowait());admitted.append(task);q.task_done()
    assert [t[0] for t in admitted]==[1,2,1,0]
    assert admitted[1][2]['page']==80
    assert q._unfinished_tasks==77


def test_seeded_page_order_is_reproducible_and_not_page_order():
    def order(seed):
        q=FairWorkQueue(['cat'],seed=seed)
        for i in range(1,50):q.put_nowait((1,i,{'id':'cat','page':i}))
        result=[]
        while not q.empty():
            task=q.at_admission(q.get_nowait());result.append(task[2]['page']);q.task_done()
        assert q._unfinished_tasks==0
        return result
    assert order('fixed')==order('fixed')
    assert order('fixed')!=list(range(1,50))
    assert order('fixed')!=order('other')
    assert sorted(order('fixed'))==list(range(1,50))


def test_fresh_workers_can_swap_all_three_lanes_without_losing_work():
    import random
    for seed in range(20):
        rng=random.Random(seed);q=FairWorkQueue(['a','b'],seed=str(seed))
        for i in range(80):q.put_nowait((rng.choice([0,1,2]),i,{'id':rng.choice(['a','b']),'page':i}))
        prefetched=[q.get_nowait() for _ in range(8)];seen=[]
        while prefetched:
            current=prefetched.pop(rng.randrange(len(prefetched)));task=q.at_admission(current)
            seen.append(task[1]);q.task_done()
            if not q.empty():prefetched.append(q.get_nowait())
        assert sorted(seen)==list(range(80)) and q._unfinished_tasks==0
