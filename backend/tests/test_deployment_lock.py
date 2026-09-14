import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows deployment uses a cross-session OS mutex')
def test_competing_deploy_process_cannot_acquire_same_runtime(tmp_path):
    script=(Path(__file__).resolve().parents[2]/'scripts'/'deployment-lock.ps1').as_posix().replace("'","''")
    root=tmp_path.as_posix().replace("'","''")
    child=f". '{script}'; try {{ $m=Enter-ZargarDeployment '{root}'; Exit-ZargarDeployment $m; exit 1 }} catch {{ exit 0 }}"
    child_quoted=child.replace("'","''")
    command=f". '{script}'; $m=Enter-ZargarDeployment '{root}'; try {{ & powershell.exe -NoProfile -Command '{child_quoted}'; if ($LASTEXITCODE -ne 0) {{ throw 'Competing owner acquired lease' }}; $nested=Enter-ZargarDeployment '{root}'; Exit-ZargarDeployment $nested }} finally {{ Exit-ZargarDeployment $m }}"
    completed=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,timeout=30,check=False)
    assert completed.returncode==0,completed.stdout+completed.stderr
