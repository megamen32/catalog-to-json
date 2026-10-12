"""Execution metadata without credentials or conversational transcripts."""
import hashlib
import importlib.metadata
from pathlib import Path
import subprocess
import sys


def program_version():
    root=Path(__file__).resolve().parents[2]
    git=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=5)
    status=subprocess.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True,timeout=5)
    files=sorted(Path(__file__).parent.rglob('*.py'))+sorted((Path(__file__).parent/'skills').rglob('SKILL.md'))
    return {'package_version':importlib.metadata.version('catalog-to-json'),
            'git_revision':git.stdout.strip() if git.returncode==0 else None,
            'dirty':bool(status.stdout.strip()) if status.returncode==0 else None,
            'source_code_sha256':hashlib.sha256(b''.join(str(p.relative_to(root)).encode()+b'\0'+p.read_bytes() for p in files)).hexdigest(),
            'python_version':sys.version.split()[0]}
