from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Strict base: unknown fields are errors, so Claude-written JSON can't smuggle in surprises."""

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class LooseModel(BaseModel):
    """For config sections that are documentation-heavy and may grow."""

    model_config = ConfigDict(extra="allow")
