import os
import nuke

out_dir = os.environ.get("OPENCUE_RENDER_OUT", "P:/projects/opencue_test/render/nuke").replace("\\", "/")
frame = int(os.environ.get("CUE_IFRAME", "1"))
if not os.path.isdir(out_dir):
    os.makedirs(out_dir)

print("Nuke version :", nuke.env.get("NukeVersionString"))
print("Frame        :", frame)
print("Output dir   :", out_dir)

chk = nuke.nodes.CheckerBoard2()
chk["format"].setValue("PC_Video")
blur = nuke.nodes.Blur(inputs=[chk])
blur["size"].setExpression("frame * 2")

w = nuke.nodes.Write(inputs=[blur])
w["file"].setValue("%s/nuke.####.png" % out_dir)
w["file_type"].setValue("png")

nuke.execute(w, frame, frame)

expected = "%s/nuke.%04d.png" % (out_dir, frame)
ok = os.path.isfile(expected)
print("Output file  :", expected)
print("Exists       :", ok, os.path.getsize(expected) if ok else 0, "bytes")
