"""Sequential project × model × case runner with immutable first-pass receipts."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from pydantic import Field
from .schema import Model
from .benchmark import BenchmarkCase, score_file
from .tools import write_json


class CaseSpec(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    source: Path
    page: int = Field(ge=1)
    fixture: Path


class ProjectSpec(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    version: str
    cwd: Path
    command: list[str] = Field(min_length=1)
    artifact: str
    stage: str = 'first_pass'
    model_receipt: str | None = None


class Suite(Model):
    cases: list[CaseSpec] = Field(min_length=1)
    projects: list[ProjectSpec] = Field(min_length=1)
    models: list[str] = Field(min_length=1)
    repeats: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=300, ge=1)
    deadline_seconds: int = Field(default=900, ge=1)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_state(project):
    def git(args):
        result = subprocess.run(['git', '-C', str(project.cwd), *args], capture_output=True, timeout=5)
        return result.stdout if result.returncode == 0 else None
    revision = git(['rev-parse', 'HEAD'])
    changes = git(['status', '--porcelain']) if revision else None
    command_files={}
    for arg in project.command:
        if '{' not in arg:
            path=(project.cwd/arg).resolve()
            if path.is_file():command_files[str(path)]=sha(path)
    return {'command_file_sha256':command_files,'git_revision': revision.decode().strip() if revision else None,
            'dirty': bool(changes) if changes is not None else None,
            'tracked_diff_sha256': hashlib.sha256(git(['diff', '--binary', 'HEAD']) or b'').hexdigest() if changes else None,
            'declared_version': project.version}


def run_suite(manifest, output, resume=False):
    manifest = Path(manifest).resolve(); output = Path(output).resolve()
    suite = Suite.model_validate_json(manifest.read_text())
    for name, items in [('case', suite.cases), ('project', suite.projects)]:
        if len({item.id for item in items}) != len(items): raise ValueError(f'Duplicate {name} IDs')
    if len(set(suite.models)) != len(suite.models): raise ValueError('Duplicate model selections')
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError('Suite output must be fresh, or use --resume')
    output.mkdir(parents=True, exist_ok=True)
    # Resolve manifest-relative paths; golden files are only consumed by the parent grader.
    for case in suite.cases:
        case.source = (manifest.parent / case.source).resolve()
        case.fixture = (manifest.parent / case.fixture).resolve()
        golden = BenchmarkCase.model_validate_json(case.fixture.read_text())
        if golden.source_sha256 != sha(case.source) or golden.page != case.page:
            raise ValueError(f'Fixture/input mismatch for {case.id}')
    for project in suite.projects:
        project.cwd = (manifest.parent / project.cwd).resolve()
        if not any('{model}' in arg for arg in project.command):raise ValueError(f'Project {project.id} must explicitly pass the selected model to its adapter')
        if not project.cwd.is_dir(): raise ValueError(f'Missing project cwd: {project.id}')
        if Path(project.artifact).is_absolute() or '..' in Path(project.artifact).parts:
            raise ValueError('Artifact must be relative to its fresh run directory')
    started = time.monotonic(); records = []; exhausted = False
    states = {project.id: project_state(project) for project in suite.projects}
    for case in suite.cases:
        for project in suite.projects:
            for model in suite.models:
                for repeat in range(1, suite.repeats + 1):
                    if time.monotonic() - started >= suite.deadline_seconds:
                        exhausted = True; break
                    identity = {'case': case.id, 'source_sha256': sha(case.source), 'page': case.page,
                                'project': project.model_dump(mode='json'), 'project_state': states[project.id],
                                'model': model, 'repeat': repeat, 'timeout_seconds': suite.timeout_seconds}
                    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                    work = output / key[:20]; receipt = work / 'run.json'
                    artifact = work / project.artifact
                    saved = json.loads(receipt.read_text()) if receipt.exists() else None
                    if saved:
                        if saved['execution_key'] != key: raise ValueError('Run directory key collision')
                        # Never replay failures or an unknown interrupted external invocation.
                        if saved['status'] == 'running': saved = {**saved, 'status': 'interrupted_unknown', 'error': 'Prior execution has unknown completion; retained without replay'}
                        if saved['status'] == 'completed' and (states[project.id]['dirty'] or not artifact.exists() or sha(artifact) != saved.get('artifact_sha256')):
                            saved = {**saved, 'status': 'artifact_unverified', 'error': 'Changed source/artifact cannot be reused; retained without replay'}
                    else:
                        work.mkdir(exist_ok=True)
                        values = {'source': str(case.source), 'page': case.page, 'model': model, 'run_dir': str(work)}
                        command = [arg.format(**values) for arg in project.command]
                        saved = {'execution_key': key, 'case_id': case.id, 'project': project.id,
                                 'project_state': states[project.id], 'model': model, 'repeat': repeat,
                                 'stage': project.stage, 'source_sha256': identity['source_sha256'],
                                 'page': case.page, 'status': 'running', 'tokens': None, 'cost': None}
                        write_json(receipt, saved); arm_started = time.monotonic()
                        with (work / 'process.log').open('wb') as log:
                            # Own process group stays in the inherited resource cgroup;
                            # it permits timeout cleanup of this arm's descendants only.
                            try:
                                proc = subprocess.Popen(command, cwd=project.cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                            except OSError as exc:
                                saved.update(status='failed', error=f'{type(exc).__name__}: {exc}')
                            else:
                                remaining = suite.deadline_seconds - (time.monotonic() - started)
                                try:
                                    code = proc.wait(timeout=min(suite.timeout_seconds, max(.001, remaining)))
                                    saved.update(status='completed' if code == 0 and artifact.exists() else 'failed', exit_code=code)
                                except subprocess.TimeoutExpired:
                                    if proc.poll() is None:
                                        os.killpg(proc.pid, signal.SIGTERM)
                                    try: proc.wait(timeout=5)
                                    except subprocess.TimeoutExpired:
                                        os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                                    saved.update(status='timed_out', error='Run deadline reached; own process group stopped')
                        saved['elapsed_seconds'] = round(time.monotonic() - arm_started, 3)
                        if saved['status'] == 'completed': saved['artifact_sha256'] = sha(artifact)
                        write_json(receipt, saved)
                    entry = dict(saved)
                    if saved['status'] == 'completed':
                        try:
                            if project.model_receipt:
                                actual=json.loads((work/project.model_receipt).read_text())
                                if actual.get('model')!=model or actual.get('source_sha256')!=identity['source_sha256'] or actual.get('physical_page')!=case.page:
                                    raise ValueError('Adapter runtime receipt contradicts selected model/source/page')
                            entry['score'] = score_file(case.fixture, artifact)
                            score_path = work / ('score-' + entry['score']['grader_sha256'][:12] + '-' + entry['score']['fixture_sha256'][:12] + '.json')
                            write_json(score_path, entry['score'])
                        except (ValueError, KeyError, OSError) as exc:
                            entry.update(status='invalid_output', error=f'{type(exc).__name__}: {exc}')
                    records.append(entry)
                    write_json(output / 'results.json', {'runs': records, 'complete': False})
                if exhausted: break
            if exhausted: break
        if exhausted: break
    expected = len(suite.cases) * len(suite.projects) * len(suite.models) * suite.repeats
    result = {'schema_version': '1.0', 'manifest_sha256': sha(manifest), 'expected_runs': expected,
              'complete': not exhausted and len(records) == expected, 'runs': records}
    write_json(output / 'results.json', result)
    return result
