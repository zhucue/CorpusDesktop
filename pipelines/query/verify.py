"""Capture the actual S0 query test run and installed CWB evidence under tmp/."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
result = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/query','-v'],cwd=ROOT,text=True,capture_output=True)
package = Path('/opt/cwb-download/cwb.deb')
report = {'recorded_at':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),
    'python':platform.python_version(),'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,
    'gold_cases':len(json.loads((ROOT/'tests/golden/query-v1.json').read_text(encoding='utf-8'))['cases']),
    'cwb_package_sha256':hashlib.sha256(package.read_bytes()).hexdigest() if package.exists() else None,
    'formal_capacity_acceptance':False}
if package.exists():
    report['packages'] = subprocess.run(['dpkg-query','-W','cwb','libpcre3','libglib2.0-0','libreadline8'],text=True,capture_output=True,check=True).stdout
target = ROOT/'tmp/query-s0'
target.mkdir(parents=True,exist_ok=True)
(target/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(result.stdout+result.stderr)
sys.exit(result.returncode)
