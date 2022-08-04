from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

from utils import convert_string_to_date


@dataclass
class Event:
    id: int = None
    type: str = None
    amount: D = None
    date: date = None
    is_last: bool = False
    is_same_date: bool = False
    state: str = None

    def __post_init__(self):
        if not isinstance(self.amount, D):
            self.amount = D(self.amount)
        if not isinstance(self.date, date):
            self.date = convert_string_to_date(self.date)
