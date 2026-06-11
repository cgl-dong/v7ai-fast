"""Authentication endpoints."""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.core.database import get_db, User
from app.core.settings import settings
from app.services.auth import AuthService

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Get current authenticated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = AuthService(db).get_user(username=username)
    if user is None:
        raise credentials_exception
    return user


@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login and get access token."""
    user = AuthService(db).authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = AuthService(db).create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer", "username": user.username}


@router.post("/register")
async def register_user(
    username: str,
    password: str,
    email: str = None,
    db: Session = Depends(get_db)
):
    """Register a new user."""
    auth_service = AuthService(db)
    
    if auth_service.get_user(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    user = auth_service.create_user(username, password, email)
    return {"message": "User created successfully", "username": user.username}


@router.get("/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Get current user info."""
    return {"username": current_user.username, "email": current_user.email, "id": current_user.id}
