from enum import StrEnum


class AnalysisClassification(StrEnum):
    CLEAN = "clean"
    UNCERTAIN = "uncertain"
    DIRTY = "dirty"
