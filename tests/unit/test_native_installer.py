from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv

ROOT=Path(__file__).resolve().parents[2]

class NativeInstallerTests(unittest.TestCase):
    def test_venv_interpreter_and_custom_state_survive_upgrade(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.scratch',prefix='native-install-') as temporary:
            root=Path(temporary);home=root/'home';home.mkdir()
            environment=root/'venv';venv.EnvBuilder(with_pip=False,symlinks=True).create(environment)
            dependencies=root/'dependencies';dependencies.mkdir()
            for name in ['requests','bs4','pycurl']:(dependencies/(name+'.py')).touch()
            python=environment/'bin/python'
            command=[str(python),str(ROOT/'scripts/install/install_native.py'),'--dependencies',str(dependencies)]
            env={**os.environ,'HOME':str(home)}
            state=root/'custom-state'
            subprocess.run(command+['--state-dir',str(state)],env=env,check=True,capture_output=True)
            (state/'keep-record').write_text('saved')
            subprocess.run(command,env=env,check=True,capture_output=True)
            manifest=json.loads((home/'.mozilla/native-messaging-hosts/org.littledrinks.qoj_vp.json').read_text())
            self.assertEqual(manifest['path'],str(state/'native-launcher.sh'))
            launcher=(state/'native-launcher.sh').read_text()
            self.assertIn('exec '+str(python)+' -m qojvp.native_host',launcher)
            self.assertEqual((state/'keep-record').read_text(),'saved')
