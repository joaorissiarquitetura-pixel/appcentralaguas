from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict
except ImportError:  # Pydantic v1 in production environments.
    ConfigDict = None


class CustomerLoginRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=30)
    password: str = Field(min_length=1, max_length=64)


class CustomerRegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    password: str = Field(min_length=4, max_length=64)
    confirm_password: str = Field(min_length=4, max_length=64)
    birth_date: str | None = None
    zip_code: str = Field(min_length=8, max_length=12)
    street: str = ""
    number: str = ""
    complement: str = ""
    neighborhood: str = ""
    ref_code: str | None = None


class ForgotPasswordRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=30)


class VerifyResetCodeRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=30)
    code: str = Field(min_length=6, max_length=12)


class ResetPasswordRequest(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(populate_by_name=True)

    reset_token: str = Field(min_length=16, max_length=200, alias="resetToken")
    new_password: str = Field(min_length=4, max_length=64, alias="newPassword")

    if ConfigDict is None:
        class Config:
            allow_population_by_field_name = True
