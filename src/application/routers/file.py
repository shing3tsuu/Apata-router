import logging
from typing import NoReturn
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response, status

from src.adapters.database.dto import CreateFileTransferDTO
from src.adapters.database.service.file import FileService
from src.adapters.encryption.service.jwt import JWTService
from src.application.models.file import (
    AcknowledgeFilesRequest,
    AcknowledgeFilesResponse,
    CompleteFileUploadResponse,
    CreateFileUploadRequest,
    FileUploadSessionResponse,
    UndeliveredFileResponse,
    UndeliveredFilesResponse,
)
from src.errors.error import (
    BaseAppError,
    ChatNotFoundError,
    ChatParticipantNotFoundError,
    FileTransferAccessDeniedError,
    FileTransferExpiredError,
    FileTransferIncompleteError,
    FileTransferNotFoundError,
    FileTransferNotReadyError,
    FileTransferOffsetConflictError,
    FileTransferValidationError,
    UserNotFoundError,
)

from .user import AuthAPI


def _raise_file_http_error(error: BaseAppError) -> NoReturn:
    if isinstance(
        error, (FileTransferNotFoundError, ChatNotFoundError, UserNotFoundError)
    ):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(
        error, (FileTransferAccessDeniedError, ChatParticipantNotFoundError)
    ):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, FileTransferExpiredError):
        status_code = status.HTTP_410_GONE
    elif isinstance(
        error,
        (
            FileTransferOffsetConflictError,
            FileTransferIncompleteError,
            FileTransferNotReadyError,
        ),
    ):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(error, FileTransferValidationError):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    raise HTTPException(status_code=status_code, detail=error.message) from error


class FileAPI:
    def __init__(self) -> None:
        self._file_router = APIRouter(prefix="/files", tags=["Files"])
        self._register_endpoints()

    def get_router(self) -> APIRouter:
        return self._file_router

    def _register_endpoints(self) -> None:
        @self._file_router.post(
            "/uploads",
            response_model=FileUploadSessionResponse,
            status_code=status.HTTP_201_CREATED,
        )
        @inject
        async def create_upload(
            request_data: CreateFileUploadRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> FileUploadSessionResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            try:
                transfer = await file_service.create_upload(
                    CreateFileTransferDTO(
                        file_id=request_data.file_id,
                        message_id=request_data.message_id,
                        sender_id=current_user_id,
                        recipient_id=request_data.recipient_id,
                        chat_id=request_data.chat_id,
                        total_size=request_data.total_size,
                        chunk_size=request_data.chunk_size,
                        encrypted_metadata=request_data.encrypted_metadata,
                        ephemeral_public_key=request_data.ephemeral_public_key,
                        ephemeral_signature=request_data.ephemeral_signature,
                    )
                )
            except BaseAppError as error:
                _raise_file_http_error(error)

            logger.info(
                "File upload created: upload=%s sender=%s recipient=%s",
                transfer.upload_id,
                current_user_id,
                transfer.recipient_id,
            )
            return FileUploadSessionResponse.model_validate(transfer)

        @self._file_router.get(
            "/uploads/{upload_id}", response_model=FileUploadSessionResponse
        )
        @inject
        async def get_upload_session(
            upload_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> FileUploadSessionResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            try:
                transfer = await file_service.get_upload_session(
                    upload_id, current_user_id
                )
            except BaseAppError as error:
                _raise_file_http_error(error)
            return FileUploadSessionResponse.model_validate(transfer)

        @self._file_router.patch(
            "/uploads/{upload_id}", response_model=FileUploadSessionResponse
        )
        @inject
        async def upload_chunk(
            upload_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            encrypted_chunk: bytes = Body(
                ..., media_type="application/offset+octet-stream"
            ),
            upload_offset: int = Header(..., alias="Upload-Offset", ge=0),
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> FileUploadSessionResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            try:
                offset = await file_service.append_chunk(
                    upload_id=upload_id,
                    sender_id=current_user_id,
                    offset=upload_offset,
                    ciphertext=encrypted_chunk,
                )
                transfer = await file_service.get_upload_session(
                    upload_id, current_user_id
                )
            except BaseAppError as error:
                _raise_file_http_error(error)

            return FileUploadSessionResponse.model_validate(
                transfer.model_copy(update={"offset": offset})
            )

        @self._file_router.post(
            "/uploads/{upload_id}/complete",
            response_model=CompleteFileUploadResponse,
        )
        @inject
        async def complete_upload(
            upload_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> CompleteFileUploadResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            try:
                transfer = await file_service.complete_upload(
                    upload_id, current_user_id
                )
            except BaseAppError as error:
                _raise_file_http_error(error)

            logger.info("File upload completed: upload=%s", upload_id)
            return CompleteFileUploadResponse(file_id=transfer.file_id)

        @self._file_router.delete("/uploads/{upload_id}")
        @inject
        async def abort_upload(
            upload_id: UUID,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> dict[str, bool]:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            try:
                aborted = await file_service.abort_upload(upload_id, current_user_id)
            except BaseAppError as error:
                _raise_file_http_error(error)
            return {"aborted": aborted}

        @self._file_router.get("/undelivered", response_model=UndeliveredFilesResponse)
        @inject
        async def get_undelivered_files(
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> UndeliveredFilesResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            transfers = await file_service.get_undelivered_files(current_user_id)
            files = [
                UndeliveredFileResponse.model_validate(transfer)
                for transfer in transfers
            ]
            return UndeliveredFilesResponse(has_files=bool(files), files=files)

        @self._file_router.post("/ack", response_model=AcknowledgeFilesResponse)
        @inject
        async def acknowledge_files(
            request_data: AcknowledgeFilesRequest,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> AcknowledgeFilesResponse:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            acknowledged = await file_service.acknowledge_files(
                current_user_id, request_data.file_ids
            )
            return AcknowledgeFilesResponse(acknowledged=acknowledged)

        @self._file_router.get("/{file_id}/chunks/{chunk_index}")
        @inject
        async def download_chunk(
            file_id: UUID,
            chunk_index: int,
            auth_api: FromDishka[AuthAPI],
            jwt_service: FromDishka[JWTService],
            file_service: FromDishka[FileService],
            logger: FromDishka[logging.Logger],
            token: str = Depends(AuthAPI.oauth2_scheme),
        ) -> Response:
            current_user_id = await auth_api.get_current_user(
                token, jwt_service, logger
            )
            try:
                ciphertext = await file_service.get_chunk(
                    file_id, current_user_id, chunk_index
                )
            except BaseAppError as error:
                _raise_file_http_error(error)
            return Response(content=ciphertext, media_type="application/octet-stream")
