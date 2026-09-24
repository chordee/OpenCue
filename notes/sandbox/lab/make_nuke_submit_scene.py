"""建立 31 篇用的 Nuke 測試場景。用法：ocrun nuke 17.0v1 Nuke17.0 -t make_nuke_submit_scene.py"""
import nuke

OUT = "C:/opencue/render/nuke_sub/"
nuke.root()["first_frame"].setValue(1)
nuke.root()["last_frame"].setValue(5)
cb = nuke.nodes.CheckerBoard2()
w1 = nuke.nodes.Write(name="WriteA", file=OUT + "a.####.png", file_type="png")
w1.setInput(0, cb)
grp = nuke.nodes.Group(name="Comp")
grp.begin()
inp = nuke.nodes.Input()
w2 = nuke.nodes.Write(name="WriteB", file=OUT + "b.####.png", file_type="png")
w2.setInput(0, inp)
grp.end()
grp.setInput(0, cb)
nuke.scriptSaveAs("C:/opencue/scenes/nuke_submit_test.nk", overwrite=1)
print("saved", nuke.root().name(), nuke.NUKE_VERSION_STRING, w2.fullName())
