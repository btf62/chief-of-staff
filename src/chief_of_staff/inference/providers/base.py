"""Provider boundary protocols and safe failure categories."""

from __future__ import annotations

from typing import Protocol

from chief_of_staff.inference.models import InferenceRequest, InferenceResult


class InferenceProvider(Protocol):
    """Application-owned provider contract."""

    provider_name: str

    def infer(self, request: InferenceRequest) -> InferenceResult:
        """Evaluate one bounded request without source or tool access."""


class InferenceProviderError(RuntimeError):
    """Base error without provider response or private evidence content."""


class InferenceDisabledError(InferenceProviderError):
    """Raised when the provider boundary is disabled."""


class InferenceConfigurationError(InferenceProviderError):
    """Raised when approved provider configuration is incomplete."""


class InferenceCredentialError(InferenceProviderError):
    """Raised when the Keychain reference is unavailable."""


class InferenceTimeoutError(InferenceProviderError):
    """Raised when the bounded provider request times out."""


class InferenceRateLimitError(InferenceProviderError):
    """Raised when the provider rejects the bounded request rate."""


class InferenceUnavailableError(InferenceProviderError):
    """Raised for a provider or transport outage."""


class InferenceRefusalError(InferenceProviderError):
    """Raised when the provider refuses the bounded classification."""


class InferenceSchemaError(InferenceProviderError):
    """Raised when provider output fails the application-owned schema."""


class InferenceModelMismatchError(InferenceProviderError):
    """Raised when a provider silently returns a different model."""
