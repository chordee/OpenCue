"""cook 一個 TOP 節點，等到有 work item 開始 cook 後取消（34 篇）。

用法：hython cancel_pdg_cook.py <hip> <TOP 節點路徑> [等待秒數，預設 40]
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
