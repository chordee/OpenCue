"""Cook a TOP node, wait until work items start cooking, then cancel (Note 34).

Usage: hython cancel_pdg_cook.py <hip> <TOP node path> [wait seconds, default 40]
"""
import collections
import sys
import time

import hou

hip, path = sys.argv[1], sys.argv[2]
wait = float(sys.argv[3]) if len(sys.argv) > 3 else 40
hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
node = hou.node(path)
node.cookWorkItems(block=False)
time.sleep(wait)
node.getPDGGraphContext().cancelCook()
time.sleep(10)
states = collections.Counter(str(w.state) for w in node.getPDGNode().workItems)
print("cancelled {0}: {1}".format(path, dict(states)))
