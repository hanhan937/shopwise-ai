"""Chat errors and AWS/Bedrock error mapping.

Users only ever see the fixed, generic messages defined here: never AWS error text, request IDs,
ARNs, account IDs, stack traces, or credential material.
"""
from __future__ import annotations

import logging

try:  # boto3 is a normal dependency; the guard only keeps this module importable without it
    import botocore.exceptions as bexc
except ImportError:  # pragma: no cover
    bexc = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Error codes the UI may offer a "Try again" for (temporary conditions).
TRANSIENT_CODES = frozenset({"ai_rate_limited", "ai_timeout", "ai_unreachable"})


class ChatError(Exception):
    """An error with a safe message and the HTTP status the API should return."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def not_configured() -> ChatError:
    return ChatError(
        503,
        "aws_credentials_missing",
        "The AI assistant isn't configured yet: no AWS credentials were found on the server. Provide credentials "
        "(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, AWS_BEARER_TOKEN_BEDROCK, or an AWS profile/role), then "
        "restart the backend. The product catalog keeps working without it.",
    )


_CREDENTIAL_PROBLEM_CODES = frozenset({
    "UnrecognizedClientException", "InvalidSignatureException", "SignatureDoesNotMatch", "ExpiredTokenException",
    "ExpiredToken", "InvalidClientTokenId", "IncompleteSignature", "MissingAuthenticationToken", "InvalidToken",
})  # fmt: skip
_ACCESS_DENIED_CODES = frozenset({"AccessDeniedException", "AccessDenied", "UnauthorizedOperation"})
_THROTTLE_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded", "ServiceQuotaExceededException",
})  # fmt: skip
_TIMEOUT_CODES = frozenset({"ModelTimeoutException", "RequestTimeout", "RequestTimeoutException"})
_PROVIDER_CODES = frozenset({
    "ServiceUnavailableException", "InternalServerException", "ModelErrorException", "ModelStreamErrorException",
})  # fmt: skip


def _timeout() -> ChatError:
    return ChatError(504, "ai_timeout", "The AI service took too long to respond. Please try again.")


def _rate_limited() -> ChatError:
    return ChatError(
        429, "ai_rate_limited",
        "The AI service is throttling requests or a quota was reached. Wait a moment and try again.",
    )


def _model_unavailable() -> ChatError:
    return ChatError(
        503, "ai_model_unavailable",
        "The configured AI model can't be used. Check BEDROCK_MODEL_ID and AWS_REGION: the model must exist and be "
        "enabled for this account in this region, and many models need a cross-region inference profile ID "
        "(for example one starting with 'us.' or 'global.').",
    )


def _from_client_error(exc: "bexc.ClientError") -> ChatError:
    response = getattr(exc, "response", None) or {}
    code = str((response.get("Error") or {}).get("Code") or "")
    http = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    # Log the code and HTTP status only: AWS messages can contain ARNs and account IDs.
    logger.warning("Bedrock request failed: %s (http=%s)", code or "unknown", http)

    if code in _ACCESS_DENIED_CODES:
        return ChatError(
            503, "bedrock_access_denied",
            "AWS denied access to Amazon Bedrock. Check that the credentials' IAM policy allows bedrock:InvokeModel "
            "for this model and region, and that the model is available to your account.",
        )
    if code in _CREDENTIAL_PROBLEM_CODES:
        return ChatError(503, "aws_credentials_invalid", "AWS rejected the server's credentials (invalid or expired). Update them and restart.")
    if code in _THROTTLE_CODES or http == 429:
        return _rate_limited()
    if code in _TIMEOUT_CODES or http in (408, 504):
        return _timeout()
    if code in {"ResourceNotFoundException", "ModelNotReadyException"}:
        return _model_unavailable()
    if code == "ValidationException":
        message = str((response.get("Error") or {}).get("Message") or "").lower()  # classified, never returned
        if any(word in message for word in ("model", "inference profile", "on-demand", "throughput")):
            return _model_unavailable()
        return ChatError(502, "ai_provider_error", "The AI service rejected the request. Please try again.")
    if code in _PROVIDER_CODES or (isinstance(http, int) and http >= 500):
        return ChatError(502, "ai_provider_error", "The AI service returned an error. Please try again.")
    if http == 403:
        return _from_client_error_access_denied()
    return ChatError(502, "ai_provider_error", "The AI service returned an error. Please try again.")


def _from_client_error_access_denied() -> ChatError:
    return ChatError(503, "bedrock_access_denied", "AWS denied access to Amazon Bedrock. Check the credentials' IAM permissions.")


def map_provider_error(exc: BaseException) -> ChatError:
    """Translate an exception raised while calling Bedrock into a safe ChatError."""
    if bexc is not None:
        if isinstance(exc, (bexc.NoCredentialsError, bexc.PartialCredentialsError, bexc.CredentialRetrievalError,
                            bexc.TokenRetrievalError, bexc.ProfileNotFound)):
            logger.warning("AWS credentials unavailable: %s", type(exc).__name__)
            return not_configured()
        if isinstance(exc, bexc.NoRegionError):
            return ChatError(503, "aws_region_missing", "No AWS region is configured. Set AWS_REGION and restart the backend.")
        if isinstance(exc, (bexc.ReadTimeoutError, bexc.ConnectTimeoutError)):
            logger.warning("Bedrock request timed out: %s", type(exc).__name__)
            return _timeout()
        if isinstance(exc, (bexc.EndpointConnectionError, bexc.ConnectionClosedError)):
            logger.warning("Bedrock endpoint unreachable: %s", type(exc).__name__)
            return ChatError(502, "ai_unreachable", "Couldn't reach the AI service. Please try again shortly.")
        if isinstance(exc, bexc.ClientError):
            return _from_client_error(exc)
        if isinstance(exc, bexc.BotoCoreError):
            logger.warning("Bedrock client error: %s", type(exc).__name__)
            return ChatError(502, "ai_provider_error", "The AI service returned an error. Please try again.")

    # Type only: exception text could contain request data, so it is never logged or returned.
    logger.error("Unexpected error while calling the AI provider: %s", type(exc).__name__)
    return ChatError(500, "internal_error", "Something went wrong while contacting the AI service.")
