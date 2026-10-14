"""Fast unit/focused integration: exact source votes, no partial or majority acceptance.

Expected30s, emergency300s; no provider requests or live queue writes.
"""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess

import pymupdf
import pytest

from catalog_json.reconciliation.consensus import (
    REQUIRED_ROLES, build_consensus, case_sha256, load_sources, save_vote, validate_pack, validate_vote,
)
from catalog_json.reconciliation.voter import (
    MODELS, adjudication_server_config, explicit_retry_policy, runtime_config, run_voter, validate_rejected_attempt,
)
from catalog_json.reconciliation.voter_tools import VoterTools, server


@pytest.fixture
def inputs(tmp_path):
    pdf = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(); page.insert_text((72, 72), "D=18.2; wire13.5-18.0")
        doc.save(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps([{"sha256": digest, "path": str(pdf)}]))
    pack = {"schema_version": "reconciliation-pack/1", "pack_id": "pilot", "cases": [
        {"case_id": "dimension", "kind": "technical", "source_sha256": digest, "physical_pages": [1],
         "ours": [{"value": "18.2", "owner": "seat"}], "oleg": [{"value": "18.2", "owner": "wire"}]},
        {"case_id": "missing", "kind": "technical", "source_sha256": digest, "physical_pages": [1],
         "ours": [], "oleg": [{"value": None, "state": "blank"}]}]}
    pack_file = tmp_path / "pack.json"; pack_file.write_text(json.dumps(pack))
    sources = load_sources(sources_file)
    payload = {"pack_id": "pilot", "verdicts": [{"case_id": c["case_id"], "case_sha256": case_sha256(c),
        "decision": "ours", "reason": "D is the clamp seat, not wire itself", "source_evidence": [
            {"source_sha256": digest, "page": 1, "bbox": [0, 0, 1, 1], "observation": "Original dimension label"}]} for c in pack["cases"]]}
    return pack, payload, sources, pack_file, sources_file


def identity(role):
    return {"role": role, "session_id": "actual-session-" + role,
            "model": MODELS.get(role, "actual-native-model"), "runtime": "isolated-test-runtime-" + role}


def voices(pack, payload, sources):
    return [validate_vote(pack, payload, identity=identity(role), sources=sources) for role in REQUIRED_ROLES]


def test_canonical_case_digest_is_order_independent_but_exact(inputs):
    pack, *_ = inputs
    case = pack["cases"][0]
    assert case_sha256(case) == case_sha256(dict(reversed(list(case.items()))))
    changed = copy.deepcopy(case); changed["ours"][0]["value"] = 18.2
    assert case_sha256(changed) != case_sha256(case)
    changed = copy.deepcopy(case); changed["ours"][0]["value"] = "18,2"
    assert case_sha256(changed) != case_sha256(case)


@pytest.mark.parametrize("mutation", ["partial", "unknown", "duplicate", "stale", "identity", "no-evidence", "wrong-source", "wrong-page"])
def test_save_refuses_incomplete_forged_or_unbound_votes(inputs, mutation):
    pack, payload, sources, *_ = inputs
    payload = copy.deepcopy(payload)
    if mutation == "partial": payload["verdicts"].pop()
    if mutation == "unknown": payload["verdicts"][0]["case_id"] = "invented"
    if mutation == "duplicate": payload["verdicts"][1] = payload["verdicts"][0]
    if mutation == "stale": payload["verdicts"][0]["case_sha256"] = "0" * 64
    if mutation == "identity": payload["identity"] = identity("codex")
    if mutation == "no-evidence": payload["verdicts"][0]["source_evidence"] = []
    if mutation == "wrong-source": payload["verdicts"][0]["source_evidence"][0]["source_sha256"] = "0" * 64
    if mutation == "wrong-page": payload["verdicts"][0]["source_evidence"][0]["page"] = 2
    with pytest.raises(ValueError): validate_vote(pack, payload, identity=identity("glm"), sources=sources)


def test_source_whitelist_checks_bytes_not_claimed_hash(inputs):
    *_, sources_file = inputs
    data = json.loads(sources_file.read_text()); data[0]["sha256"] = "0" * 64
    sources_file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash mismatch"): load_sources(sources_file)


def test_four_real_envelopes_required_and_no_majority(inputs):
    pack, payload, sources, *_ = inputs
    votes = voices(pack, payload, sources)
    result = build_consensus(pack, votes[:3])
    assert not result["complete"] and not result["all_resolved"]
    assert result["cases"][0]["missing_roles"] == ["minimax"]
    assert build_consensus(pack, votes)["all_resolved"]
    other = copy.deepcopy(payload); other["verdicts"][0]["decision"] = "oleg"
    votes[-1] = validate_vote(pack, other, identity=identity("minimax"), sources=sources)
    result = build_consensus(pack, votes)
    assert result["complete"] and not result["all_resolved"]
    assert result["cases"][0]["decision"] == "unresolved"
    assert result["cases"][1]["consensus"]
    with pytest.raises(ValueError): build_consensus(pack, [payload] * 4)
    with pytest.raises(ValueError): build_consensus(pack, [votes[0]] * 4)
    # Four role labels with one reused session are not four independent voices.
    same_session = []
    for role in REQUIRED_ROLES:
        fake_identity = identity(role); fake_identity["session_id"] = "one-session"
        same_session.append(validate_vote(pack, payload, identity=fake_identity, sources=sources))
    with pytest.raises(ValueError, match="session"): build_consensus(pack, same_session)
    wrong_model = identity("glm"); wrong_model["model"] = "openai.some-other-provider"
    with pytest.raises(ValueError, match="model identity"):
        validate_vote(pack, payload, identity=wrong_model, sources=sources)


def test_tampering_stale_input_and_unreadable_do_not_pass(inputs):
    pack, payload, sources, *_ = inputs
    votes = voices(pack, payload, sources)
    forged = copy.deepcopy(votes); forged[0]["identity"]["role"] = "minimax"
    with pytest.raises(ValueError, match="receipt"): build_consensus(pack, forged)
    changed = copy.deepcopy(pack); changed["cases"][0]["ours"] = []
    with pytest.raises(ValueError, match="pack SHA"): build_consensus(changed, votes)
    payload = copy.deepcopy(payload); payload["verdicts"][0]["decision"] = "unresolved"
    assert not build_consensus(pack, voices(pack, payload, sources))["all_resolved"]


def test_selected_null_is_distinct_and_rounds_cannot_mix(inputs, tmp_path):
    pack, payload, sources, *_ = inputs
    payload = copy.deepcopy(payload)
    for v in payload["verdicts"]: v["decision"] = "neither"; v["selected_value"] = None
    assert build_consensus(pack, voices(pack, payload, sources))["cases"][0]["selected_value"] is None
    votes = []
    for i, role in enumerate(REQUIRED_ROLES):
        p = save_vote(pack, payload, identity=identity(role), sources=sources, output_dir=tmp_path, round_number=1 if i else 2)
        votes.append(json.loads(p.read_text()))
    with pytest.raises(ValueError, match="rounds"): build_consensus(pack, votes)


def test_mcp_tools_deliver_source_then_validate_complete_save(inputs, tmp_path):
    pack, payload, sources, pack_file, sources_file = inputs
    context = VoterTools(pack_path=pack_file, sources_path=sources_file, identity=identity("glm"), output_dir=tmp_path / "votes")
    assert context.get_cases()["case_sha256"]["dimension"] == case_sha256(pack["cases"][0])
    assert not context.save_verdict(payload)["saved"]
    digest = pack["cases"][0]["source_sha256"]
    image = context.render(digest, 1)
    assert image.data
    context.render(digest, 1, [0, 0, .5, .5], 90)
    partial = copy.deepcopy(payload); partial["verdicts"].pop()
    assert not context.save_verdict(partial)["saved"] and not context.receipt.exists()
    assert context.save_verdict(payload)["saved"]
    before = context.receipt.read_bytes()
    assert not context.save_verdict(payload)["saved"]
    assert context.receipt.read_bytes() == before
    native = json.loads(before)
    assert native["identity"] == identity("glm")
    # MCP advertises exactly four tools; parser/plugin/server discovery never runs.
    tools = asyncio.run(server(context).list_tools())
    assert {t.name for t in tools} == {"get_cases", "view_page", "zoom_page", "save_verdict"}


def test_runtime_configuration_rejects_non_coding_endpoint(tmp_path):
    import yaml
    config = tmp_path / "provider.yaml"
    config.write_text(yaml.safe_dump({"zai": {"base_url": "https://api.z.ai/api/coding/paas/v4/", "api_key": "fixture"},
                                  "mcp": {"servers": {"unwanted": {"command": "never"}}}, "agent_plugins": ["never"]}))
    result = runtime_config(config, "glm")
    assert result["mcp"]["servers"] == {} and result["llm_retries"] == 0
    assert "agent_plugins" not in result and "anthropic" not in result
    config.write_text(yaml.safe_dump({"zai": {"base_url": "https://api.z.ai/api/paas/v4/"}}))
    with pytest.raises(ValueError): runtime_config(config, "glm")


@pytest.mark.parametrize("role,provider,variable", [("glm", "zai", "ZAI_API_KEY"), ("minimax", "anthropic", "MINIMAX_API_KEY")])
def test_missing_credentials_fail_before_claim_or_http(tmp_path, monkeypatch, role, provider, variable):
    import yaml
    from catalog_json.reconciliation.voter import ENDPOINTS, deny_http_requests
    config = tmp_path / "provider.yaml"
    config.write_text(yaml.safe_dump({provider: {"base_url": ENDPOINTS[role][1], "api_key": "${" + variable + "}"}}))
    monkeypatch.delenv(variable, raising=False)
    output = tmp_path / "no-claims"
    with deny_http_requests() as attempts:
        with pytest.raises(ValueError, match=variable):
            asyncio.run(run_voter(pack_path=tmp_path / "not-read-pack.json", sources_path=tmp_path / "not-read-sources.json",
                                 output_dir=output, role=role, config_path=config))
    assert attempts == [] and not output.exists()
    monkeypatch.setenv(variable, "  ")
    with pytest.raises(ValueError, match="missing or empty"): runtime_config(config, role)


@pytest.mark.parametrize("role,provider,variable,other", [("glm", "zai", "ZAI_API_KEY", "MINIMAX_API_KEY"),
                                                       ("minimax", "anthropic", "MINIMAX_API_KEY", "ZAI_API_KEY")])
def test_only_selected_provider_credentials_are_resolved(tmp_path, monkeypatch, role, provider, variable, other):
    import yaml
    from catalog_json.reconciliation.voter import ENDPOINTS
    config = tmp_path / "provider.yaml"
    original = {"zai": {"base_url": ENDPOINTS["glm"][1], "api_key": "${ZAI_API_KEY}"},
                "anthropic": {"base_url": ENDPOINTS["minimax"][1], "api_key": "${MINIMAX_API_KEY}"}}
    config.write_text(yaml.safe_dump(original))
    monkeypatch.setenv(variable, "fixture-selected-credential")
    monkeypatch.delenv(other, raising=False)
    resolved = runtime_config(config, role)
    assert resolved[provider]["api_key"] == "fixture-selected-credential"
    assert (set(resolved) & {"zai", "anthropic"}) == {provider}
    assert yaml.safe_load(config.read_text()) == original  # Never mutate the protected input.
    original[provider]["api_key"] = "${MALFORMED.NAME}"
    config.write_text(yaml.safe_dump(original))
    with pytest.raises(ValueError, match="unresolved"): runtime_config(config, role)


def rejected_attempt_fixture(tmp_path, pack, role="glm", round_number=2):
    import time
    runtime = tmp_path / case_sha256(pack) / f"round{round_number}" / "runtime" / role
    runtime.mkdir(parents=True)
    claim = {"role": role, "pack_sha256": case_sha256(pack), "round_number": round_number, "session_id": "actual-old-session"}
    execution = {"status": "unknown", "identity": {"role": role, "session_id": claim["session_id"], "model": MODELS[role]},
                 "pack_sha256": case_sha256(pack), "started_at": time.time() - 2, "finished_at": time.time() - 1,
                 "receipt": None, "receipt_sha256": None}
    turn = {"stop_reason": "error", "tool_calls": None, "tool_results": None,
            "channels": {"fast-agent-error": [{"type": "text", "text": "AuthenticationError status=401; Error code: 401"}]}}
    for name, value in [("claim.json", claim), ("execution.json", execution), ("turn1.json", turn)]:
        (runtime / name).write_text(json.dumps(value))
    return runtime


@pytest.mark.parametrize("mutation", ["unfinished", "different-source", "different-session", "other-http", "no-sdk-confirmation",
                                     "tool-call", "tool-result", "later-turn", "accepted-receipt", "success"])
def test_transport_retry_refuses_unknown_or_accepted_work(inputs, tmp_path, mutation):
    pack, *_ = inputs
    runtime = rejected_attempt_fixture(tmp_path, pack)
    turn = json.loads((runtime / "turn1.json").read_text())
    execution = json.loads((runtime / "execution.json").read_text())
    if mutation == "unfinished": execution.pop("finished_at")
    if mutation == "different-source": execution["pack_sha256"] = "0" * 64
    if mutation == "different-session": execution["identity"]["session_id"] = "another-session"
    if mutation == "other-http": turn["channels"]["fast-agent-error"][0]["text"] = "status=500; Error code: 500"
    if mutation == "no-sdk-confirmation": turn["channels"] = {}; turn["content"] = [{"text": "source contains401"}]
    if mutation == "tool-call": turn["tool_calls"] = [{"name": "save_verdict"}]
    if mutation == "tool-result": turn["tool_results"] = [{"saved": True}]
    if mutation == "later-turn": (runtime / "turn2.json").write_text(json.dumps(turn))
    if mutation == "accepted-receipt":
        receipts = runtime.parent.parent / "receipts"; receipts.mkdir(); (receipts / "glm.json").write_text("{}")
    if mutation == "success": turn["stop_reason"] = "end_turn"
    (runtime / "turn1.json").write_text(json.dumps(turn)); (runtime / "execution.json").write_text(json.dumps(execution))
    with pytest.raises(ValueError):
        validate_rejected_attempt(runtime, pack_sha256=case_sha256(pack), role="glm", round_number=2)


def test_transport_attempt2_keeps_semantic_round_and_previous_bytes(inputs, tmp_path, monkeypatch):
    import yaml
    from catalog_json.reconciliation.voter import ENDPOINTS
    pack, _, _, pack_file, sources_file = inputs
    output = tmp_path / "votes"
    runtime = rejected_attempt_fixture(output, pack)
    frozen = {p.name: p.read_bytes() for p in runtime.iterdir()}
    basis = validate_rejected_attempt(runtime, pack_sha256=case_sha256(pack), role="glm", round_number=2)
    assert basis["classification"] == "provider_rejected_http401"
    config = tmp_path / "provider.yaml"
    config.write_text(yaml.safe_dump({"zai": {"base_url": ENDPOINTS["glm"][1], "api_key": "fixture"}}))
    class NoProviderLaunch(Exception): pass
    async def prevent_model_process(*args, **kwargs): raise NoProviderLaunch()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", prevent_model_process)
    with pytest.raises(NoProviderLaunch):
        asyncio.run(run_voter(pack_path=pack_file, sources_path=sources_file, output_dir=output,
                             role="glm", config_path=config, round_number=2, attempt_number=2))
    new = runtime.parent / "glm-attempt2"
    assert new.parents[3] == output  # Same depth as attempt1; same canonical round receipt.
    claim = json.loads((new / "claim.json").read_text())
    assert claim["round_number"] == 2 and claim["attempt_number"] == 2
    assert claim["retry_basis"] == basis and claim["session_id"] != "actual-old-session"
    assert all((runtime / name).read_bytes() == value for name, value in frozen.items())
    assert not (runtime.parent.parent / "receipts" / "glm.json").exists()


def test_sdk_unknown_retry_is_disabled_and_429_is_observable():
    import httpx
    from openai import AsyncOpenAI
    calls = []

    async def scenario():
        async def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "limited", "type": "rate_limit"}})
        with explicit_retry_policy(lambda delay: calls.append(delay)):
            async with AsyncOpenAI(api_key="fixture", base_url="https://fixture.invalid", max_retries=5,
                                   http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
                assert client.max_retries == 0
                with pytest.raises(Exception):
                    await client.chat.completions.create(model="fixture", messages=[{"role": "user", "content": "fixture"}])
    asyncio.run(scenario())
    assert len([v for v in calls if isinstance(v, httpx.Request)]) == 1
    assert 2 in calls


def test_real_stdio_consumer_saves_only_a_complete_bound_vote(inputs, tmp_path):
    """Focused integration; actual MCP subprocess and image/save protocol, no LLM."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    pack, payload, _, pack_file, sources_file = inputs
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(json.dumps(identity("minimax")))
    output = tmp_path / "native-stdio"

    async def consumer():
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "catalog_json.reconciliation.voter_tools", "--pack", str(pack_file),
            "--sources", str(sources_file), "--identity", str(identity_file), "--output", str(output)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                assert {t.name for t in (await session.list_tools()).tools} == {"get_cases", "view_page", "zoom_page", "save_verdict"}
                cases = await session.call_tool("get_cases", {})
                assert not cases.is_error and pack["cases"][0]["case_id"] in str(cases)
                viewed = await session.call_tool("view_page", {"source_sha256": pack["cases"][0]["source_sha256"], "page": 1})
                assert not viewed.is_error and any(c.type == "image" for c in viewed.content)
                partial = copy.deepcopy(payload); partial["verdicts"].pop()
                rejected = await session.call_tool("save_verdict", {"data": partial})
                assert json.loads(next(c.text for c in rejected.content if c.type == "text"))["saved"] is False
                accepted = await session.call_tool("save_verdict", {"data": payload})
                result = json.loads(next(c.text for c in accepted.content if c.type == "text"))
                assert result["saved"] is True
                return result

    result = asyncio.run(consumer())
    receipt = json.loads(Path(result["receipt"]).read_text())
    assert receipt["identity"] == identity("minimax")
    assert receipt["pack_sha256"] == case_sha256(pack)
    assert len(receipt["payload"]["verdicts"]) == len(pack["cases"])


@pytest.mark.parametrize("role", ["glm", "minimax"])
def test_native_fastagent_boots_only_adjudication_tools_without_network(inputs, tmp_path, monkeypatch, role):
    """Provider initialization + real MCP attachment, explicitly forbid HTTP/API calls."""
    import httpx
    import yaml
    from fast_agent import FastAgent
    from fast_agent.mcp.mcp_aggregator import MCPAttachOptions
    from catalog_json.models import register_model_capabilities
    from catalog_json.reconciliation.voter import ENDPOINTS
    _, _, _, pack_file, sources_file = inputs
    who = tmp_path / "identity.json"; who.write_text(json.dumps(identity(role)))
    provider, endpoint = ENDPOINTS[role]
    config = tmp_path / "fast-agent.yaml"
    # Use the production builder: the old handwritten test config injected
    # PYTHONPATH that the actual worker forgot, hiding installed-runtime failure.
    config.write_text(yaml.safe_dump({provider: {"base_url": endpoint, "api_key": "fixture"},
        "llm_retries": 0, "mcp": {"servers": {"adjudication":
            adjudication_server_config(tmp_path, tmp_path / "votes", 1)}}}))

    async def forbidden_http(*args, **kwargs):
        raise AssertionError("No model/network request is authorized in this test")
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_http)
    register_model_capabilities()
    fast = FastAgent("preflight", config_path=str(config), parse_cli_args=False, quiet=True,
                     workspace=tmp_path, home=tmp_path / "home", skills_directory=[])
    fast.agent(name=role, model=MODELS[role], instruction="Source-first adjudication", servers=["adjudication"],
               skills=[], shell=False, subagents=False, harness_tools=False, human_input=False)(lambda: None)

    async def boot():
        async with fast.run() as app:
            await app.attach_mcp_server(role, "adjudication", options=MCPAttachOptions(startup_timeout_seconds=20))
            result = await app[role].list_tools()
            assert len(result.tools) == 4
            assert all(any(name in t.name for name in ("get_cases", "view_page", "zoom_page", "save_verdict")) for t in result.tools)
    asyncio.run(boot())


def test_actual_installed_runtime_cli_env_cwd_limits_without_http(inputs, tmp_path):
    """Regression for real pilot: installed1524 package lacks reconciliation."""
    import yaml
    root = Path(__file__).resolve().parents[1]
    python = root / ".tmp/full-digitization/semantic-v1.5.24/env/bin/python"
    if not python.exists():
        pytest.skip("Actual retained1524 interpreter not available")
    pack, _, _, pack_file, sources_file = inputs
    runtime = tmp_path / "retained-attempt"
    runtime.mkdir()
    (runtime / "pack.json").write_bytes(pack_file.read_bytes())
    (runtime / "sources.json").write_bytes(sources_file.read_bytes())
    (runtime / "identity.json").write_text(json.dumps(identity("glm")))
    (runtime / "claim.json").write_text(json.dumps({"role": "glm", "round_number": 1, "pack_sha256": case_sha256(pack)}))
    (runtime / "provider.yaml").write_text(yaml.safe_dump({"zai": {
        "base_url": "https://api.z.ai/api/coding/paas/v4/", "api_key": "fixture"}}))
    legacy = adjudication_server_config(runtime, tmp_path / "votes", 1, python=str(python))
    legacy.pop("env"); legacy.pop("cwd")
    (runtime / "fast-agent.yaml").write_text(yaml.safe_dump({"mcp": {"servers": {"adjudication": legacy}}}))
    frozen = {p.name: p.read_bytes() for p in runtime.iterdir()}
    for saved in (True, False):
        proof_dir = tmp_path / ("saved-proof" if saved else "fixed-proof")
        args = [str(python), "-m", "catalog_json.reconciliation.voter", "--preflight-runtime", str(runtime),
                "--proof-dir", str(proof_dir)]
        if saved: args.append("--saved-server")
        run = subprocess.run(args, cwd=runtime, env={**os.environ, "PYTHONPATH": str(root / "src")},
                             capture_output=True, timeout=60)
        proof = json.loads((proof_dir / "startup-proof.json").read_text())
        assert run.returncode == (2 if saved else 0)
        assert proof["http_requests_attempted"] == proof["http_requests_sent"] == 0
        assert proof["generate_called"] is False and proof["retained_attempt_unchanged"]
        assert proof["actual_cwd"] == str(runtime)
        assert proof["actual_address_space_limit"] == [2 * 1024**3] * 2
        assert len(proof["actual_cpu_affinity"]) == 1
        assert proof["status"] == ("startup_failed" if saved else "passed")
        assert len(proof["tools"]) == (0 if saved else 4)
    assert all((runtime / name).read_bytes() == value for name, value in frozen.items())
