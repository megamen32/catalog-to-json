"""Execute one pinned operator job in the persistent unit's finite resource budget."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    job=json.loads(Path(sys.argv[1]).read_text())
    command=job['command']
    if not command or any(not isinstance(arg,str) or not arg for arg in command):
        raise ValueError('Job command must be a nonempty argv vector')
    for filename,digest in job['file_sha256'].items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest()!=digest:
            raise ValueError('Pinned job input changed; retain results and reconcile before resuming')
    environment=dict(os.environ)
    for name in job.get('unset_environment',[]):environment.pop(name,None)
    environment.update(job.get('environment',{}))
    os.chdir(job['cwd'])
    os.execvpe(command[0],command,environment)


if __name__=='__main__':main()
