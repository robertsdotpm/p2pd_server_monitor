from typing_extensions import TypedDict
from typing import Any, List, Union
from pydantic import BaseModel, field_validator, model_validator
from p2pd import *
from fqdn import FQDN
from .dealer_defs import *

def add_validator(field_name: str, cls: type, func):
    setattr(
        cls, 
        f"validate_{field_name}",
        field_validator(field_name, mode="before")(func)
    )
    cls.model_rebuild()

def validate_af(cls, v):
    if v not in VALID_AFS:
        raise ValueError("af must be in valid afs if not None")
    return v

def validate_table_type(cls, v):
    if v not in TABLE_TYPES:
        raise ValueError("table types must be in table types")
    return v

def validate_ip(cls, v):
    if v not in (None, "", "0"):
        ensure_ip_is_public(v)
    return v

def validate_time(cls, v):
    if v:
        if v < 1735689600 or v > 32503680000:
            raise ValueError("invalid time field for status.")
    return v

class AliasType(BaseModel):
    id: int
    af: int
    fqn: str
    ip: str | None
    group_id: int | None
    status_id: int | None
    table_type: int

    @field_validator("fqn")
    @classmethod
    def validate_fqn(cls, v):
        if not FQDN(v):
            raise ValueError("invalid fqn value")
        return v

class RecordType(BaseModel):
    id: int
    table_type: int
    type: int
    af: int
    proto: int | None
    ip: str | None
    port: int
    user: str | None
    password: str | None
    alias_id: int | None
    status_id: int | None
    group_id: int | None
    score: int

    @field_validator("type")
    @classmethod
    def validate_record_type(cls, v):
        if v not in SERVICE_TYPES:
            raise ValueError("invalid record type")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v):
        if not valid_port(v):
            raise ValueError("invalid port")
        return v

    @field_validator("proto")
    @classmethod
    def validate_proto(cls, v):
        if v is not None and v not in (1, 2):
            raise ValueError("proto must be 1 or 2 if not None")
        return v
    
class StatusType(BaseModel):
    id: int
    row_id: int
    table_type: int
    status: int
    last_status: int
    test_no: int
    failed_tests: int
    last_success: int
    last_uptime: int
    uptime: int
    max_uptime: int

    @field_validator("status")
    @classmethod
    def validate_status_type(cls, v):
        if v not in STATUS_TYPES:
            raise ValueError("status types must be in status types")
        return v

    @model_validator(mode="after")
    def validate_sanity(self):
        if self.max_uptime < self.uptime:
            raise ValueError("max_uptime must be >= uptime")

        if self.test_no < self.failed_tests:
            raise ValueError("test_no must be >= failed_tests")
        
        return self

class MetaGroup(BaseModel):
    id: int
    table_type: int
    af: int
    group: list[Union[RecordType, AliasType]]

for field_name in ("last_status", "last_success", "last_uptime",):
    add_validator(field_name, StatusType, validate_time)

add_validator("af", AliasType, validate_af)
add_validator("af", RecordType, validate_af)
add_validator("af", MetaGroup, validate_af)
add_validator("table_type", AliasType, validate_table_type)
add_validator("table_type", RecordType, validate_table_type)
add_validator("table_type", StatusType, validate_table_type)
add_validator("table_type", MetaGroup, validate_table_type)
add_validator("ip", AliasType, validate_ip)
add_validator("ip", RecordType, validate_ip)