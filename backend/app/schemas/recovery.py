from pydantic import BaseModel, Field, model_validator


class RecoveryPolicy(BaseModel):
    startup_seconds: float = Field(default=30, ge=5, le=300, allow_inf_nan=False)
    input_stall_seconds: float = Field(default=15, ge=3, le=300, allow_inf_nan=False)
    output_stall_seconds: float = Field(default=15, ge=3, le=300, allow_inf_nan=False)
    io_timeout_seconds: float = Field(default=10, ge=1, le=120, allow_inf_nan=False)
    retry_initial_seconds: float = Field(default=2, ge=1, le=30, allow_inf_nan=False)
    retry_max_seconds: float = Field(default=30, ge=1, le=300, allow_inf_nan=False)
    stable_seconds: float = Field(default=30, ge=5, le=300, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent_deadlines(self):
        if self.retry_initial_seconds > self.retry_max_seconds:
            raise ValueError("Initial retry delay must not exceed the maximum retry delay")
        if self.io_timeout_seconds > self.startup_seconds:
            raise ValueError("I/O timeout must not exceed the startup deadline")
        return self
