"""Runtime object construction for parsed run configs."""

from __future__ import annotations

from typing import Any

from securebench.adapters import get_adapter
from securebench.candidates import (
    OpenAICompatibleChatClient,
    OpenAICompatibleChatConfig,
    StaticCandidateProducer,
    TextCompletionProducer,
    WorkspaceAgentPatchProducer,
)
from securebench.environment import ensure_environment_image
from securebench.errors import ConfigError
from securebench.runners import CodeGenerationRunner, GitHubPatchRunner, MultipleChoiceRunner, Runner
from securebench.sandboxes import DockerSandbox


def build_adapter(config: Any) -> Any:
    return get_adapter_or_config_error(config.adapter.id)


def build_producer(config: Any) -> Any:
    if config.producer.type == "static":
        return StaticCandidateProducer(_required_str(config.producer.config, "text", "producer.config"))

    if config.producer.type == "openai_compatible":
        client = OpenAICompatibleChatClient(
            OpenAICompatibleChatConfig(
                model=_required_str(config.producer.config, "model", "producer.config"),
                base_url=str(config.producer.config.get("base_url", "https://api.openai.com/v1")),
                api_key_env=str(config.producer.config.get("api_key_env", "OPENAI_API_KEY")),
                timeout=_optional_float(config.producer.config.get("timeout")),
                temperature=_optional_float(config.producer.config.get("temperature", 0.0)),
                system_prompt=str(
                    config.producer.config.get(
                        "system_prompt",
                        "Return only the letter of the correct choice.",
                    )
                ),
                extra_body=_optional_dict(config.producer.config.get("extra_body")),
            )
        )
        return TextCompletionProducer(client, name="openai-compatible")

    if config.producer.type == "workspace_agent_patch":
        producer_config = config.producer.config
        model = _optional_str(producer_config.get("model"))
        replay_file = _optional_str(producer_config.get("replay_file"))
        if model is None and replay_file is None:
            raise ConfigError("producer.config requires either model or replay_file")
        api_key_env = str(producer_config.get("api_key_env", "OPENAI_API_KEY"))
        image = config.environment.image
        ensure_environment_image(
            image=image,
            python_version=config.environment.python,
            packages=config.environment.packages,
        )
        return WorkspaceAgentPatchProducer(
            sandbox_factory=lambda: DockerSandbox(
                image=image,
                env_names=() if replay_file is not None else (api_key_env,),
                **config.environment.producer_sandbox_policy().docker_kwargs(),
            ),
            model=model,
            replay_file=replay_file,
            repo_dir=str(producer_config.get("repo_dir", "repo")),
            task_file=str(producer_config.get("task_file", "SECUREBENCH_TASK.md")),
            base_url=str(producer_config.get("base_url", "https://api.openai.com/v1")),
            api_key_env=api_key_env,
            max_steps=_optional_positive_int(
                producer_config.get("max_steps"),
                default=40,
                field="producer.config.max_steps",
            ),
            max_tool_output=_optional_positive_int(
                producer_config.get("max_tool_output"),
                default=12_000,
                field="producer.config.max_tool_output",
            ),
            command_timeout=_optional_float_default(
                producer_config.get("command_timeout"),
                default=60.0,
                field="producer.config.command_timeout",
            ),
            request_timeout=_optional_float(
                producer_config.get("request_timeout", producer_config.get("timeout", 60.0))
            ),
            temperature=_optional_float(producer_config.get("temperature", 0.0)),
            allow_commands=_optional_str_tuple(producer_config.get("allow_commands"), "producer.config.allow_commands"),
            deny_commands=_optional_str_tuple(producer_config.get("deny_commands"), "producer.config.deny_commands"),
            setup_commands=config.environment.producer_setup_commands(),
            timeout=_optional_float(producer_config.get("timeout")),
        )

    raise ConfigError(f"Unsupported producer type {config.producer.type!r}")


def build_runner(config: Any) -> Runner:
    if config.runner.type == "multiple_choice":
        return MultipleChoiceRunner()
    if config.runner.type == "code_generation":
        return CodeGenerationRunner()
    if config.runner.type == "github_patch":
        runner_config = config.runner.config or {}
        image = config.environment.image
        ensure_environment_image(
            image=image,
            python_version=config.environment.python,
            packages=config.environment.packages,
        )
        return GitHubPatchRunner(
            image=image,
            repo_dir=str(runner_config.get("repo_dir", "repo")),
            sandbox_kwargs=config.environment.runner_sandbox_policy().docker_kwargs(),
            setup_commands=config.environment.runner_setup_commands(),
            test_commands=_optional_str_tuple(runner_config.get("test_commands"), "runner.config.test_commands"),
            apply_hidden_patches=_optional_str_tuple(
                runner_config.get("apply_hidden_patches"),
                "runner.config.apply_hidden_patches",
            ),
            test_group_names=_optional_str_tuple(
                runner_config.get("test_group_names"),
                "runner.config.test_group_names",
            ),
            test_command_template=_optional_str(runner_config.get("test_command_template")),
            timeout=_optional_float_default(
                runner_config.get("timeout"),
                default=120.0,
                field="runner.config.timeout",
            ),
        )
    raise ConfigError(f"Unsupported runner type {config.runner.type!r}")


def get_adapter_or_config_error(adapter_id: str) -> Any:
    try:
        return get_adapter(adapter_id)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc


def _required_str(data: dict[str, Any], key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{section}.{key} must be a non-empty string")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("Optional string field must be a string when provided")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _optional_positive_int(value: Any, *, default: int, field: str) -> int:
    if value is None:
        return default
    return _positive_int(value, field)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("Optional numeric field must be a number when provided")
    return float(value)


def _optional_float_default(value: Any, *, default: float, field: str) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} must be a number")
    return float(value)


def _optional_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("Optional object field must be an object when provided")
    return value


def _optional_str_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{field} must be a list of non-empty strings")
    return tuple(value)
