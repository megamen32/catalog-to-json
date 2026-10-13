"""Alternate first passes and repairs, rotating catalogues at actual admission.

Workers may prefetch before the provider gate opens. Choose again after admission,
without cancelling a native call or changing Queue unfinished-task accounting.
"""
import asyncio


class FairWorkQueue(asyncio.Queue):
    def __init__(self, catalogues):
        super().__init__()
        self.catalogues = list(catalogues)
        self.next_lane = 1  # first pass; priorities 0=repair, 1=first pass
        self.catalogue_cursor = {0: 0, 1: 0}

    def at_admission(self, current):
        available = [current, *self._queue]
        lane = self.next_lane
        if not any(task[0] == lane for task in available):
            lane = 1 - lane
        self.next_lane = 1 - lane
        candidates = [task for task in available if task[0] == lane]
        start = self.catalogue_cursor[lane]
        for offset in range(len(self.catalogues)):
            index = (start + offset) % len(self.catalogues)
            catalogue = self.catalogues[index]
            choices = [task for task in candidates if task[2]['id'] == catalogue]
            if choices:
                selected = min(choices, key=lambda task: task[1])
                self.catalogue_cursor[lane] = (index + 1) % len(self.catalogues)
                break
        else:
            raise ValueError('Queued work belongs to an unknown catalogue')
        if selected is not current:
            # One queued and one prefetched obligation exchange ownership.
            self._queue.remove(selected)
            self._queue.appendleft(current)
        return selected
