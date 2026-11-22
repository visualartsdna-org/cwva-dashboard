"""Provider access for the whole dashboard (law 7).

Nothing outside this package constructs a request to a model provider, holds a
provider credential, or names a model. A workflow names a TASK; `config/
ai_profiles.rson` says what answers it.
"""

from .profiles import DEFAULT_PROFILES_PATH, TaskProfile, load_profiles
from .service import AIService, AIUnavailable, Completion, read_api_key

__all__ = ["AIService", "AIUnavailable", "Completion", "TaskProfile",
           "load_profiles", "read_api_key", "DEFAULT_PROFILES_PATH"]
