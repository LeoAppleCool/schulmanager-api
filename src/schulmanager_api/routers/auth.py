from fastapi import APIRouter, Depends, HTTPException, Response

from schulmanager_api.dependencies import get_auth_service, get_current_principal, get_provider
from schulmanager_api.models.schemas import AuthRequest, RefreshTokenRequest, SessionInfo, TokenResponse
from schulmanager_api.providers.base import SchulmanagerProvider
from schulmanager_api.services.security import AuthPrincipal, JWTAuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: AuthRequest,
    provider: SchulmanagerProvider = Depends(get_provider),
    auth_service: JWTAuthService = Depends(get_auth_service),
) -> TokenResponse:
    context = await provider.login(payload)
    role = auth_service.decide_role(context.email)

    bundle, session_info = auth_service.issue_tokens(context=context, role=role)
    return TokenResponse(
        access_token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        expires_in=int((bundle.access_expires_at - session_info.created_at).total_seconds()),
        refresh_expires_in=int((bundle.refresh_expires_at - session_info.created_at).total_seconds()),
        session=session_info,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshTokenRequest,
    auth_service: JWTAuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        bundle, session_info = auth_service.refresh_tokens(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return TokenResponse(
        access_token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        expires_in=int((bundle.access_expires_at - session_info.created_at).total_seconds()),
        refresh_expires_in=int((bundle.refresh_expires_at - session_info.created_at).total_seconds()),
        session=session_info,
    )


@router.post("/logout", status_code=204)
async def logout(
    principal: AuthPrincipal = Depends(get_current_principal),
    auth_service: JWTAuthService = Depends(get_auth_service),
) -> Response:
    auth_service.revoke_account(principal.account_id)
    return Response(status_code=204)


@router.get("/me", response_model=SessionInfo)
async def me(principal: AuthPrincipal = Depends(get_current_principal)) -> SessionInfo:
    return SessionInfo(
        account_id=principal.account_id,
        email=principal.email,
        role=principal.role,
        school_id=principal.school_id,
        student_ids=[student.id for student in principal.context.students],
        created_at=principal.created_at,
        expires_at=principal.expires_at,
    )
