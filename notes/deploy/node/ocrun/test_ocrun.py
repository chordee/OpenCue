"""python -m unittest test_ocrun   (run inside this directory)"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

import ocrun

BINDIR = os.path.dirname(sys.executable)
PROGRAM = os.path.splitext(os.path.basename(sys.executable))[0]


class OcrunTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        config = os.path.join(self.tmp, "dcc.toml")
        with open(config, "w") as f:
            f.write('[env]\nSTUDIO_LICENSE = "5053@lic"\n'
                    "[maya]\n\"2027\" = '%s'\n" % BINDIR)
        # Restored after each test, whatever the test changes.
        environ = unittest.mock.patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)
        os.environ["OPENCUE_DCC_CONFIG"] = config
        os.environ["TMP"] = self.tmp
        os.environ.pop("TEMP", None)
        os.environ.pop("STUDIO_LICENSE", None)

    def run_py(self, code, product="maya"):
        out = os.path.join(self.tmp, "out.txt")
        rc = ocrun.main([product, "2027", PROGRAM, "-c",
                         "import os,sys\nopen(sys.argv[1],'w').write(repr(%s))" % code,
                         out])
        with open(out) as f:
            return rc, f.read()

    def test_runs_program_and_returns_exit_code(self):
        rc = ocrun.main(["maya", "2027", PROGRAM, "-c", "import sys; sys.exit(3)"])
        self.assertEqual(rc, 3)

    def test_environment(self):
        rc, env = self.run_py("{k: os.environ.get(k) for k in "
                              "['MAYA_DISABLE_CER', 'STUDIO_LICENSE', 'TEMP']}")
        self.assertEqual(rc, 0)
        self.assertEqual(eval(env), {"MAYA_DISABLE_CER": "1",
                                     "STUDIO_LICENSE": "5053@lic",
                                     "TEMP": self.tmp})

    def test_job_environment_wins_over_config(self):
        os.environ["STUDIO_LICENSE"] = "job@lic"
        rc, env = self.run_py("os.environ.get('STUDIO_LICENSE')")
        self.assertEqual(rc, 0)
        self.assertEqual(eval(env), "job@lic")

    def test_arguments_with_spaces_pass_through(self):
        out = os.path.join(self.tmp, "a b.txt")
        rc = ocrun.main(["maya", "2027", PROGRAM, "-c",
                         "import sys; open(sys.argv[1], 'w').write(sys.argv[2])",
                         out, "x y"])
        with open(out) as f:
            self.assertEqual(f.read(), "x y")

    def run_captured(self, code):
        stdout = sys.stdout
        sys.stdout = io.TextIOWrapper(io.BytesIO())
        try:
            rc = ocrun.main(["maya", "2027", PROGRAM, "-c", code])
            sys.stdout.flush()
            return rc, sys.stdout.buffer.getvalue().decode()
        finally:
            sys.stdout = stdout

    def test_fail_pattern_fails_a_zero_exit(self):
        rc, out = self.run_captured(
            "print('00:01 | ERROR | aborting render because this is a batch render')")
        self.assertEqual(rc, 1)
        self.assertIn("aborting render because", out)
        self.assertIn("[ocrun] failing the frame", out)

    def test_output_passes_through_and_exit_code_is_kept(self):
        rc, out = self.run_captured("import sys; print('hello'); sys.exit(4)")
        self.assertEqual(rc, 4)
        self.assertIn("hello", out)
        self.assertNotIn("failing the frame", out)

    def test_unknown_version_or_program(self):
        self.assertEqual(ocrun.main(["maya", "2024", PROGRAM]), 127)
        self.assertEqual(ocrun.main(["houdini", "22.0.429", "hython"]), 127)

    def test_program_only_from_bindir(self):
        with open(os.path.join(self.tmp, "decoy.exe"), "w") as f:
            f.write("")
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.assertEqual(ocrun.main(["maya", "2027", "decoy"]), 127)
        finally:
            os.chdir(cwd)

    def test_program_with_a_path_is_rejected(self):
        self.assertEqual(ocrun.main(["maya", "2027", sys.executable]), 127)
        self.assertEqual(ocrun.main(["maya", "2027", os.path.join("..", os.path.basename(BINDIR),
                                                                  PROGRAM)]), 127)
        self.assertEqual(ocrun.main(["maya", "2027", "no_such_program"]), 127)

    def test_console_script(self):
        # Runs the same way through the installed entry point, when present.
        exe = os.path.join(BINDIR, "ocrun")
        if not (os.path.exists(exe) or os.path.exists(exe + ".exe")):
            self.skipTest("ocrun is not installed in this environment")
        rc = subprocess.call([exe, "maya", "2027", PROGRAM, "-c", "import sys; sys.exit(5)"])
        self.assertEqual(rc, 5)


if __name__ == "__main__":
    unittest.main()
