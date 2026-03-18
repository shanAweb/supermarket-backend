"""Authentication routes — signup, login, refresh, me, OAuth, password reset."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.db.user import User
from app.models.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issue_tokens(user: User) -> TokenResponse:
    """Create access + refresh tokens for a user."""
    uid = str(user.id)
    return TokenResponse(
        access_token=create_access_token(uid),
        refresh_token=create_refresh_token(uid),
    )


# ---------------------------------------------------------------------------
# Task 7.1 — Signup
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        company=body.company,
    )
    db.add(user)
    await db.flush()  # populate user.id before issuing tokens

    return _issue_tokens(user)


# ---------------------------------------------------------------------------
# Task 7.2 — Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    return _issue_tokens(user)


# ---------------------------------------------------------------------------
# Task 7.3 — Token Refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    user_id = payload.get("sub")
    token_type = payload.get("type")

    if not user_id or token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return _issue_tokens(user)


# ---------------------------------------------------------------------------
# Task 7.4 — Get Current User
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Task 7.5 — OAuth Endpoints (Google & GitHub)
# ---------------------------------------------------------------------------

class _OAuthPayload:
    """Common OAuth handling: exchange code, upsert user, return tokens."""

    @staticmethod
    async def _upsert_oauth_user(
        db: AsyncSession,
        email: str,
        first_name: str,
        last_name: str,
    ) -> User:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            return user

        # Create new user — no password needed for OAuth users
        user = User(
            email=email,
            password_hash="",  # OAuth-only account
            first_name=first_name,
            last_name=last_name,
        )
        db.add(user)
        await db.flush()
        return user


@router.post("/oauth/google", response_model=TokenResponse)
async def oauth_google(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a Google authorization code for JWT tokens.

    In production this calls Google's token endpoint to verify the code
    and retrieve user info. Currently accepts the user info directly
    for development.
    """
    import httpx

    try:
        # Exchange code for Google tokens
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.cors_origins_list[0] + "/auth/google/callback",
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            # Get user info from Google
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google OAuth failed: {exc}",
        ) from exc

    user = await _OAuthPayload._upsert_oauth_user(
        db,
        email=userinfo["email"],
        first_name=userinfo.get("given_name", ""),
        last_name=userinfo.get("family_name", ""),
    )
    return _issue_tokens(user)


@router.post("/oauth/github", response_model=TokenResponse)
async def oauth_github(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a GitHub authorization code for JWT tokens."""
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for GitHub access token
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            access_token = token_data.get("access_token")
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="GitHub OAuth failed: no access token returned",
                )

            # Get user info from GitHub
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_resp.raise_for_status()
            gh_user = user_resp.json()

            # Get primary email (may be private)
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            emails_resp.raise_for_status()
            emails = emails_resp.json()
            primary_email = next(
                (e["email"] for e in emails if e.get("primary")),
                gh_user.get("email"),
            )

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"GitHub OAuth failed: {exc}",
        ) from exc

    if not primary_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not retrieve email from GitHub account",
        )

    name_parts = (gh_user.get("name") or "").split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    user = await _OAuthPayload._upsert_oauth_user(
        db,
        email=primary_email,
        first_name=first_name,
        last_name=last_name,
    )
    return _issue_tokens(user)


# ---------------------------------------------------------------------------
# Task 7.6 — Password Reset
# ---------------------------------------------------------------------------

def _create_reset_token(email: str) -> str:
    """Create a short-lived token for password reset (15 minutes)."""
    from jose import jwt as jose_jwt

    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {"sub": email, "exp": expire, "type": "reset"}
    return jose_jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Generate a password reset token.

    In production this would send the token via email.
    In development the token is returned directly in the response.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Always return 200 to prevent email enumeration
    if not user:
        return {"message": "If an account with that email exists, a reset link has been sent."}

    reset_token = _create_reset_token(user.email)

    if settings.APP_ENV == "development":
        return {
            "message": "Reset token generated (dev mode).",
            "reset_token": reset_token,
        }

    # TODO: Send email with reset link in production
    return {"message": "If an account with that email exists, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Validate a reset token and update the user's password."""
    payload = decode_token(body.token)
    email = payload.get("sub")
    token_type = payload.get("type")

    if not email or token_type != "reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user.password_hash = hash_password(body.new_password)
    await db.flush()

    return {"message": "Password has been reset successfully."}
