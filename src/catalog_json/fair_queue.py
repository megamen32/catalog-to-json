"""Alternate first passes and repairs, rotating catalogues at actual admission.

Workers may prefetch before the provider gate opens. Choose again after admission,
without cancelling a native call or changing Queue unfinished-task accounting.
"""
import asyncio
import hashlib


REVIEW_ORDER = 'alternate first passes and repairs; fresh repairs before backlog with fairness; seeded random pages favouring smaller inventories'


class FairWorkQueue(asyncio.Queue):
    def __init__(self, catalogues, seed=None):
        super().__init__()
        self.catalogues = list(catalogues)
        self.next_lane = 1  # first pass; priorities 0=repair, 1=first pass
        self.catalogue_cursor = {0: 0, 1: 0}
        self.seed = seed
        self.next_repair = 2  # fresh candidate, then historical repair backlog
        self.catalogue_cursor[2] = 0

    def first_pass_rank(self, task):
        if self.seed is None:return task[1]
        item=task[2];record=item.get('record',{})
        page=record.get('pdf_page',item.get('page',task[1]))
        random_rank=int.from_bytes(hashlib.sha256(f'{self.seed}|{item["id"]}|{page}'.encode()).digest()[:8],'big')/2**64
        content=record.get('content') or {}
        cells=sum(len(row.get('cells',[])) for table in content.get('tables',[]) for row in table.get('rows',[]))
        labels=sum(any(c.isnumeric() for c in label) for f in content.get('figures',[]) for label in f.get('labels',[]))
        # Random weighted order, not a hard exclusion of complex pages.
        return random_rank*(1+min(cells/100+labels/8,8))

    def at_admission(self, current):
        available = [current, *self._queue]
        lane = self.next_lane
        def in_lane(task,lane):return (task[0]==1) if lane==1 else (task[0] in (0,2))
        if not any(in_lane(task,lane) for task in available):
            lane = 1 - lane
        self.next_lane = 1 - lane
        candidates = [task for task in available if in_lane(task,lane)]
        if lane==0:
            lane=self.next_repair
            if not any(task[0]==lane for task in candidates):lane=0 if lane==2 else 2
            self.next_repair=0 if lane==2 else 2
            candidates=[task for task in candidates if task[0]==lane]
        start = self.catalogue_cursor[lane]
        for offset in range(len(self.catalogues)):
            index = (start + offset) % len(self.catalogues)
            catalogue = self.catalogues[index]
            choices = [task for task in candidates if task[2]['id'] == catalogue]
            if choices:
                selected = min(choices, key=self.first_pass_rank if lane==1 else lambda task:task[1])
                self.catalogue_cursor[lane] = (index + 1) % len(self.catalogues)
                break
        else:
            raise ValueError('Queued work belongs to an unknown catalogue')
        if selected is not current:
            # One queued and one prefetched obligation exchange ownership.
            self._queue.remove(selected)
            self._queue.appendleft(current)
        return selected
