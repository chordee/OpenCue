"""以 hython cook 一個 TOP 節點並列出結果（34 篇）。

用法：hython cook_pdg_node.py <hip> <TOP 節點路徑>
"""
import collections
import sys
import time

import hou

hip, path = sys.argv[1], sys.argv[2]
hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
node = hou.node(path)
start = time.time()
node.cookWorkItems(block=True)
states = collections.Counter(str(w.state) for w in node.getPDGNode().workItems)
print("cooked {0} in {1:.0f}s: {2}".format(path, time.time() - start, dict(states)))
for w in node.getPDGNode().workItems[:3]:
    print("  ", w.name, w.state, [r.path for r in w.outputFiles], w.attribValue("square"))
for n in node.parent().children():
    if n.errors() or n.warnings():
        print("  node", n.name(), n.errors(), n.warnings())
