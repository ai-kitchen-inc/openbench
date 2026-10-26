# Configuration Guide

OpenBench has two related configuration systems: general configuration and provider configuration.

## General Configuration

`openbench.core.config.Config` loads YAML or JSON files, expands environment variables, and supports dot-notation access.

```python
from openbench.core import Config

config = Config().load("openbench.yaml").load_env()
model = config.get("llm.default_model", "gemini-2.5-flash")
```

Environment variables with the `OPENBENCH_` prefix can be loaded with `load_env()`. For example, `OPENBENCH_LLM_MODEL` becomes `llm.model`.

The CLI exposes configuration commands:

```bash
openbench config init
openbench config set llm.default_model gemini-2.5-flash
openbench config get llm.default_model
openbench config show
openbench config validate
```

## Provider Configuration

`ProviderService` manages named provider configurations for provider types such as LLM, vector, storage, embedding, search, output, and tools.

```python
from openbench.core import ProviderConfig, ProviderType, get_provider_service

service = get_provider_service()
service.configure(
    ProviderConfig(
        name="google-default",
        provider_type=ProviderType.LLM,
        provider="google",
        plugin_type="chat",
        credentials={"api_key": "your-key"},
        is_default=True,
    )
)
```

CLI equivalents:

```bash
openbench provider add google-default --type llm --provider google --plugin-type chat --api-key "$GOOGLE_API_KEY" --default
openbench provider list
openbench provider show google-default
openbench provider test google-default
```

## Credential Storage

Provider configuration is persisted below `~/.openbench/`. If the `security` extra is installed, credential values are encrypted at rest with `cryptography` and Fernet.

```bash
python -m pip install -e ".[security]"
```

Do not commit provider config files or API keys.

## Model Registry

Models are described with `ModelInfo` records and can be managed through code or CLI commands:

```bash
openbench models list
openbench models show gemini-2.5-flash
openbench models defaults
```
