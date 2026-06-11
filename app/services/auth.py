"""User authentication service."""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt as _bcrypt
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.core.database import User, get_db


class AuthService:
    """Service for user authentication."""

    def __init__(self, db: Session):
        self.db = db

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password hash."""
        return _bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )

    def get_password_hash(self, password: str) -> str:
        """Hash a password."""
        return _bcrypt.hashpw(
            password.encode("utf-8"),
            _bcrypt.gensalt(),
        ).decode("utf-8")

    def get_user(self, username: str) -> Optional[User]:
        """Get user by username."""
        return self.db.query(User).filter(User.username == username).first()

    def create_user(self, username: str, password: str, email: str = None) -> User:
        """Create a new user."""
        hashed_password = self.get_password_hash(password)
        user = User(
            username=username,
            hashed_password=hashed_password,
            email=email,
            created_at=datetime.now()
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now() + expires_delta
        else:
            expire = datetime.now() + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
        return encoded_jwt

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Authenticate user."""
        user = self.get_user(username)
        if not user or not self.verify_password(password, user.hashed_password):
            return None
        return user
