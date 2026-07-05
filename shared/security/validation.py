from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from .exceptions import ValidationError as CustomValidationError


class SecureModel(BaseModel):
    """Base class that forbids any extra fields.

    All external inputs should inherit from this class to ensure strict validation.
    """

    model_config = ConfigDict(extra="forbid")

    def __init__(self, **data: object) -> None:
        try:
            super().__init__(**data)
        except PydanticValidationError as e:
            # Raise the project's custom ValidationError to keep a consistent API
            raise CustomValidationError(str(e)) from e
