from typing import Literal
from pydantic import BaseModel, validator
from .validators import validate_int, validate_str, validate_float


class GeneralConfig(BaseModel):
    station_name: str

    # validators
    _val_station_name = validator("station_name", pre=True, allow_reuse=True)(
        validate_str(min_len=3, max_len=64),
    )

    class Config:
        extra = "forbid"


# -----------------------------------------------------------------------------


class HardwareConfig(BaseModel):
    pumped_litres_per_round: float

    # validators
    _val_pumped_litres_per_round = validator(
        "pumped_litres_per_round", pre=True, allow_reuse=True
    )(
        validate_float(minimum=0.0001, maximum=1),
    )

    class Config:
        extra = "forbid"


# -----------------------------------------------------------------------------


class AirInletConfig(BaseModel):
    number: Literal[1, 2, 3, 4]
    direction: int
    pipe_length: float

    # validators
    _val_number = validator("number", pre=True, allow_reuse=True)(
        validate_int(allowed=[1, 2, 3, 4]),
    )
    _val_direction = validator("direction", pre=True, allow_reuse=True)(
        validate_int(minimum=0, maximum=359),
    )
    _val_pipe_length = validator("pipe_length", pre=True, allow_reuse=True)(
        validate_float(minimum=1, maximum=100),
    )

    class Config:
        extra = "forbid"


# -----------------------------------------------------------------------------


class CalibrationGasConfig(BaseModel):
    valve_number: Literal[1, 2, 3, 4]
    concentration: float

    # validators
    _val_valve_number = validator("valve_number", pre=True, allow_reuse=True)(
        validate_int(allowed=[1, 2, 3, 4]),
    )
    _val_concentration = validator("concentration", pre=True, allow_reuse=True)(
        validate_float(minimum=0, maximum=10000),
    )

    class Config:
        extra = "forbid"


class CalibrationConfig(BaseModel):
    flushing_minutes: float
    litres_per_minute: float
    gases: list[CalibrationGasConfig]

    # validators
    _val_flushing_minutes = validator("flushing_minutes", pre=True, allow_reuse=True)(
        validate_int(minimum=0, maximum=60),
    )
    _val_litres_per_minute = validator("litres_per_minute", pre=True, allow_reuse=True)(
        validate_float(minimum=0, maximum=30),
    )

    class Config:
        extra = "forbid"


# -----------------------------------------------------------------------------


class HeatedEnclosureConfig(BaseModel):
    device_path: str
    target_temperature: float
    allowed_deviation: float

    # validators
    _val_device_path = validator("device_path", pre=True, allow_reuse=True)(
        validate_str()
    )
    _val_target_temperature = validator(
        "target_temperature", pre=True, allow_reuse=True
    )(
        validate_float(minimum=0, maximum=50),
    )
    _val_allowed_deviation = validator("allowed_deviation", pre=True, allow_reuse=True)(
        validate_float(minimum=0, maximum=10),
    )

    class Config:
        extra = "forbid"


# -----------------------------------------------------------------------------


class Config(BaseModel):
    """The config.json for each sensor"""

    version: Literal["0.1.0"]
    revision: int
    general: GeneralConfig
    hardware: HardwareConfig
    air_inlets: list[AirInletConfig]
    calibration: CalibrationConfig
    heated_enclosure: HeatedEnclosureConfig

    # validators
    _val_version = validator("version", pre=True, allow_reuse=True)(
        validate_str(allowed=["0.1.0"]),
    )
    _val_revision = validator("revision", pre=True, allow_reuse=True)(
        validate_int(minimum=0, maximum=2_147_483_648),
    )

    class Config:
        extra = "forbid"
