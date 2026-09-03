from pydantic import BaseModel


class JwtResponse(BaseModel):

    accessToken: str

    refreshToken: str

    userId: str

    email: str

    role: str

    expiresIn: int

    newUser: bool

    emailVerified: bool

    profileComplete: bool = False
