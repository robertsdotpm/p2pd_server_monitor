"""
There's some neat computer science here.

If deque was used it would have:
    Log(n) deletes.
    Log(1) popleft.
    Log(1) pop.

which is decent, but the Log(n) isn't ideal and can still be improved.
If you use a doubly-linked list over a deque and have a hashtable
of Node pointers in the list mapped by name / ID, you can then
have Log(1) deletes, too. So moving items between queues is all Log(1).

Would not work if the linked-list was indexed by positional offsets
over memory addresses as you would have to update each offset for a
delete. This is a very neat trick used by high performance schedulers.
"""

from .dealer_defs import *
from .linked_list import *

class WorkQueue:
    def __init__(self):
        self.queues = {
            STATUS_INIT: LinkedList(),
            STATUS_AVAILABLE: LinkedList(),
            STATUS_DEALT: LinkedList()
        }

        # work_id -> (queue_name, node reference)
        self.index = {} 

    def add_work(self, work_id, payload, queue_name):
        node = self.queues[queue_name].append((work_id, payload))
        self.index[work_id] = (queue_name, node)

    def move_work(self, work_id, to_queue):
        # Remove from existing linked-list.
        from_queue, node = self.index[work_id]
        self.queues[from_queue].remove(node)

        # Add to end of target linked_list.
        new_node = self.queues[to_queue].append(node.value)
        self.index[work_id] = (to_queue, new_node)

    def remove_work(self, work_id):
        queue_name, node = self.index.pop(work_id)
        self.queues[queue_name].remove(node)

    def pop_available(self):
        node = self.queues[STATUS_AVAILABLE].popleft()
        if not node:
            return None
        
        work_id, payload = node.value
        self.index.pop(work_id, None)
        return work_id, payload

"""

wq = WorkQueue()
wq.add_work("job1", {"task": 123}, STATUS_INIT)
wq.add_work("job2", {"task": 456}, STATUS_AVAILABLE)

# Move job2 to dealt
wq.move_work("job2", STATUS_DEALT)

# Pop from available
print(wq.pop_available())  # None (because job2 was moved)

# Iterate over dealt
for work_id, payload in wq.queues[STATUS_DEALT]:
    print(work_id, payload)

"""