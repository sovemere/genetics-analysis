"""Pinned native PLINK 1.9 for ROH; shares the PLINK subprocess safety machinery."""

from typing import ClassVar

from genetics.external.plink2 import Plink2


class Plink19(Plink2):
    tool_id: ClassVar[str] = "plink19"
    executable_name: ClassVar[str] = "plink"
    label: ClassVar[str] = "PLINK 1.9"
