class AuthException(Exception):

    status_code: int = 401

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidCredentialsException(AuthException):

    status_code = 401


class EmailNotVerifiedException(AuthException):

    status_code = 403


class AccountInactiveException(AuthException):

    status_code = 403


class EmailAlreadyExistsException(AuthException):

    status_code = 409


class InvalidVerificationTokenException(AuthException):

    status_code = 400

class EmailAlreadyVerifiedException(
    AuthException
):

    pass


class InvalidPasswordResetTokenException(AuthException):

    status_code = 400