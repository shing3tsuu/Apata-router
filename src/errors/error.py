from datetime import UTC, datetime
from typing import Any


class BaseAppError(Exception):
    def __init__(self, message: str, context: dict[str, Any] | None = None):
        self.message = message
        self.context = context or {}
        self.timestamp = datetime.now(UTC).isoformat()
        super().__init__(self.message)


class UserAlreadyExistsError(BaseAppError):
    pass


class UserNotRegisteredError(BaseAppError):
    pass


class UserNotFoundError(BaseAppError):
    pass


class ContactAlreadyExistsError(BaseAppError):
    pass


class ContactNotFoundError(BaseAppError):
    pass


class ChatAlreadyExistsError(BaseAppError):
    pass


class ChatNotFoundError(BaseAppError):
    pass


class ChatParticipantAlreadyExistsError(BaseAppError):
    pass


class ChatParticipantNotFoundError(BaseAppError):
    pass


class ChatPermissionDeniedError(BaseAppError):
    pass


class FileTransferNotFoundError(BaseAppError):
    pass


class FileTransferAccessDeniedError(BaseAppError):
    pass


class FileTransferExpiredError(BaseAppError):
    pass


class FileTransferOffsetConflictError(BaseAppError):
    pass


class FileTransferIncompleteError(BaseAppError):
    pass


class FileTransferNotReadyError(BaseAppError):
    pass


class FileTransferValidationError(BaseAppError):
    pass


class InfrastructureError(BaseAppError):
    def __init__(
        self,
        message: str,
        original_error: Exception | None = None,
        context: dict[str, Any] | None = None,
    ):
        self.original_error = original_error
        context = context or {}
        if original_error:
            context.update(
                {
                    "original_error_type": original_error.__class__.__name__,
                    "original_error_message": str(original_error),
                }
            )
        super().__init__(message, context)


class DatabaseError(InfrastructureError):
    pass


class InvalidAccessTokenTypeError(ValueError):
    """Raised when a JWT is not an access token."""


class MissingAccessTokenSubjectError(ValueError):
    """Raised when an access token does not identify a user."""
