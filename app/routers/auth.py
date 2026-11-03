import hashlib
import re
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from app.database import create_user, delete_session, get_user_by_email
from app.security import current_user, hash_password, issue_session, verify_password


class LoginCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        local, separator, domain = value.rpartition("@")
        labels = domain.split(".")
        if (
            not separator
            or not 1 <= len(local) <= 64
            or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or local.startswith(".")
            or local.endswith(".")
            or ".." in local
            or len(labels) < 2
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
        ):
            raise ValueError("Enter a valid email address")
        return value


class RegistrationCredentials(LoginCredentials):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot contain only spaces")
        return value


class UserResponse(BaseModel):
    id: str
    email: str


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


def prevent_auth_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(prevent_auth_caching)])


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(credentials: RegistrationCredentials) -> dict[str, object]:
    email = credentials.email
    if get_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user_id = str(uuid4())
    try:
        create_user(user_id, email, hash_password(credentials.password))
    except sqlite3.IntegrityError:
        # The unique constraint also handles simultaneous requests for one email.
        if get_user_by_email(email) is not None:
            raise HTTPException(status_code=409, detail="An account with this email already exists") from None
        raise
    return {"token": issue_session(user_id), "user": {"id": user_id, "email": email}}


@router.post("/login", response_model=AuthResponse)
def login(credentials: LoginCredentials) -> dict[str, object]:
    email = credentials.email
    user = get_user_by_email(email)
    if user is None:
        # Spend the same password-hashing work for unknown accounts.
        hash_password(credentials.password)
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"token": issue_session(user["id"]), "user": {"id": user["id"], "email": user["email"]}}


@router.get("/me", response_model=UserResponse)
def me(user: dict[str, str] = Depends(current_user)) -> dict[str, object]:
    return {"id": user["id"], "email": user["email"]}


@router.post("/logout")
def logout(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    delete_session(hashlib.sha256(user["token"].encode()).hexdigest())
    return {"status": "signed out"}
