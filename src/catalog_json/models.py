"""Verified native provider metadata, scoped to this process (no SDK/global config patch)."""
from fast_agent.llm.model_database import ModelDatabase,ModelParameters
from fast_agent.llm.provider_types import Provider
from fast_agent.llm.reasoning_effort import ReasoningEffortSpec,ReasoningEffortSetting


def register_model_capabilities():
    # Verified 2026-10-11: https://platform.minimax.io/docs/api-reference/text-anthropic-api
    # FastAgent 0.10.43 otherwise treats unknown Anthropic model names as text-only
    # and strips image content. max_output_tokens is our conservative client cap.
    ModelDatabase.register_runtime_model_params('MiniMax-M3.1-Flash-Preview',ModelParameters(
        context_window=1_000_000,max_output_tokens=16384,
        tokenizes=['text/plain','image/jpeg','image/png','image/webp','image/gif'],
        default_provider=Provider.ANTHROPIC,json_mode=None,reasoning='anthropic_thinking',
        reasoning_effort_spec=ReasoningEffortSpec(kind='effort',allowed_efforts=['low','medium','high','xhigh','max'],default=ReasoningEffortSetting(kind='effort',value='low')),
        anthropic_thinking_field_required=True,anthropic_thinking_disable_supported=False))
    ModelDatabase.register_runtime_model_params('MiniMax-M3',ModelParameters(
        context_window=1_000_000,max_output_tokens=16384,
        tokenizes=['text/plain','image/jpeg','image/png','image/webp','image/gif'],
        default_provider=Provider.ANTHROPIC,json_mode=None))
