from enum import Enum


class WorkType(str, Enum):
    FREELANCE = "FREELANCE"
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    OPEN_TO_ALL = "OPEN_TO_ALL"
