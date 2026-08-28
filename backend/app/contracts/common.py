from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeKey(StrEnum):
    N01 = "N01"; N02 = "N02"; N03 = "N03"; N04 = "N04"; N05 = "N05"
    N06 = "N06"; N07 = "N07"; N08 = "N08"; N09 = "N09"; N10 = "N10"
    N11 = "N11"; N11_5 = "N11.5"; N12 = "N12"; N13 = "N13"; N14 = "N14"
    N15 = "N15"; N16 = "N16"; N17 = "N17"; N18 = "N18"; N19 = "N19"; N20 = "N20"


class NodeStatus(StrEnum):
    PENDING = "PENDING"; RUNNING = "RUNNING"; SUCCEEDED = "SUCCEEDED"; FAILED = "FAILED"
