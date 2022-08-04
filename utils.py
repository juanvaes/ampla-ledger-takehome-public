import datetime
import csv
from decimal import Decimal


def convert_string_to_date(
    string: str,
    string_date_format: str = "%Y-%m-%d"
) -> datetime.date:
    """Converts a string date into a date objects"""
    return datetime.datetime.strptime(string, string_date_format).date()


def convert_date_to_string(
    date: datetime.date,
    string_date_format: str = "%Y-%m-%d"
) -> datetime.date:
    """Converts a date object into a string"""
    return date.strftime(string_date_format)

def get_date_difference(
    current_date: datetime.date,
    last_date: datetime.date
) -> datetime.timedelta:
    return (current_date - last_date)


def csv_events_to_list_tuple(path_name):
    events = []
    with open(path_name) as f:
        csv_reader = csv.reader(f)
        for index, row in enumerate(csv_reader):
            event = ((index+1), row[0], float(row[2]), row[1])
            events.append(event)
    return events