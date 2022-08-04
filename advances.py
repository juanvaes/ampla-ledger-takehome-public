from collections import OrderedDict
from datetime import date
from decimal import Decimal as D
from typing import Iterable, Tuple, Union

from event import Event
from utils import convert_string_to_date, get_date_difference


class AdvanceCalculator:
    LOAN_INTEREST_RATE = D(0.00035)
    EVENT_PAYMENT_TYPE = "payment"
    EVENT_ADVANCE_TYPE = "advance"
    EVENT_TRUNCATED_TYPE = "truncated"
    # self.advance_balance, self.interest_payable_balance, self.interest_paid, self.payments_for_future

    def __init__(self) -> None:
        self.advance_balance = D(0)
        self.interest_payable_balance = D(0)
        self.interest_paid = D(0)
        self.payments_for_future = D(0)
        self.advances = (
            OrderedDict()
        )  # key is the identifier, value is the advance balue

        # To make reverts (Taking information of the previous state)
        self.last_advance_balance = D(0)
        self.last_interest_payable_balance = D(0)
        self.last_interest_paid = D(0)
        self.last_payments_for_future = D(0)

        self.advance_count = 0
        self.last_event = None
        self.last_advance = None

    @property
    def daily_interest(self) -> D:
        """Returns the daily interest based on the current balance"""
        return self.LOAN_INTEREST_RATE * self.advance_balance

    def get_accrued_interests(
        self, event_date: date, last_event_date: date, inclusive: bool = False
    ) -> D:
        """Returns the accrued interest from event.date to next_event.date

        :param inclusive: Helps you to calculate the accrued interest from the exact
                          difference between event.date and next_event.date or you can
                          calculate the accrued interest with 1 day of difference.
        """
        # How many days of difference exists between the current event date and last event date?
        date_delta: int = get_date_difference(event_date, last_event_date).days
        if inclusive:
            return date_delta * self.daily_interest
        return (date_delta - 1) * self.daily_interest

    def _decrease_oldest_active_balance(self, remaining_amount: D):
        """Decreases the oldest active balance from a specified amount (remaining_amount)

        Notes:
          - We iterate over the advances mapping and we check if each of the advance is paid.
            If we find an advance that is not paid (is_paid=False), we select that advance to pay it,
            that could be the overall amount without money for future payments, or the overall amount
            of the advance, or just a portion of the advance.
          - There could be a case where we identify that all advances are paid, the remaining amount
            is greater than zero (Decimal(0)) and we are not using the money from an event, in that case
            we just add that amount (the whole remaining_amount) to the self.payments_for_future attribute.
        """
        is_using_payment_from_event = False
        # Decrease the oldest active advance balance
        for advance_id, advance_data in self.advances.items():
            # If advance is paid, go to the next advance
            if advance_data["is_paid"]:
                continue

            advance_data_current_balance = advance_data["Current Balance"]
            decreased_advance_balance = advance_data_current_balance - remaining_amount

            # all advance is paid
            if decreased_advance_balance == D(0):
                self.advances[advance_id]["Current Balance"] = D(0)
                self.advances[advance_id]["is_paid"] = True
                self.advance_balance -= remaining_amount
                remaining_amount = D(0)
                break

            # A portion of the advance is paid
            elif decreased_advance_balance > D(0):
                self.advances[advance_id]["Current Balance"] -= remaining_amount
                self.advance_balance -= remaining_amount
                remaining_amount = D(0)

                # What if we pay totally and advance but there is still money to pay another one (self.payments_for_future)
                # In this case if we can pay another advance but we can just pay a portion of it, this block of code handles
                # the update of 'self.payments_for_future' to be zero (0).
                if is_using_payment_from_event:
                    self.payments_for_future = D(0)
                break

            # All the advance is paid and there is money to pay another advance
            elif decreased_advance_balance < D(0):
                self.advances[advance_id]["Current Balance"] = D(0)
                self.advances[advance_id]["is_paid"] = True
                self.advance_balance -= advance_data_current_balance
                self.payments_for_future = abs(decreased_advance_balance)
                remaining_amount = self.payments_for_future
                is_using_payment_from_event = True

        # If we receive a payment and we want to decrease the advances, there could be a case
        # when we already paid all the advances and we are not reusing and event.amount
        # So we just add this amount to the self.payments for future
        advances_paid = [advance["is_paid"] for _, advance in self.advances.items()]
        if (
            remaining_amount > D(0)
            and all(advances_paid)
            and not is_using_payment_from_event
        ):
            self.payments_for_future += remaining_amount

    def _execute_payment_flow(
        self,
        current_event: Event,
        increase_interest: bool = True,
    ):
        """Executes the payment logic.

        Steps: Anytime a payment is received, it is applied in the following manner
        ------
          1. To reduce the "interest payable balance" for the customer (if any)
          2. Any remaining amount of the repayment is applied to reduce the "advance balance"
             of the oldest active advance, and if there is any remaining amount it reduces the
             amount of the following (second oldest) advance, and so on,
          3. after all advances have been repaid - if there is still some amount of the repayment
             available, the remaining amount of the repayment should be credited towards to immediately
             paying down future advances, when they are made.
        """
        # Payment Logic
        # ---------------------

        # Remaining amount of payment reduces the oldest active balance (iterative)
        # --------------------------------------------------------------------------
        if self.interest_payable_balance > D(0):
            remaining_amount = current_event.amount - self.interest_payable_balance

            # if remaining_amount equals to zero, customer paid all the interests
            # so we just update the interest_paid attribute.
            if remaining_amount == D(0):
                self.interest_paid += current_event.amount

            # if remaining_amount less than zero, he just paid a portion of the interests
            elif remaining_amount < D(0):
                self.interest_paid += current_event.amount
                self.interest_payable_balance = abs(remaining_amount)

            # if remaining_amount greater than zero, customer paid the interests so we decrease the balances
            elif remaining_amount > D(0):
                # Update interests of today event
                self.interest_paid += self.interest_payable_balance
                self.interest_payable_balance = D(0)

                self._decrease_oldest_active_balance(remaining_amount)

                # Note: This block of code triggers when we pay all of the advances and we still have money
                #       and depending of the amount of the 'overall_advance_balance' we update its value
                #       and the value for 'payments_for_future'.
                if self.payments_for_future > D(0) and self.advance_balance > D(0):
                    advance_balance_overall_remaining_diff = (
                        self.advance_balance - self.payments_for_future
                    )

                    # Final difference is equal
                    if advance_balance_overall_remaining_diff == D(0):
                        self.advance_balance = D(0)
                        self.payments_for_future = D(0)

                    # Final difference pays a portion of the overall advance balance
                    elif advance_balance_overall_remaining_diff > D(0):
                        self.advance_balance -= advance_balance_overall_remaining_diff
                        self.payments_for_future = D(0)

                    # Final difference pays all the advance balance and the remaining amount is given to the user account
                    elif advance_balance_overall_remaining_diff < D(0):
                        self.advance_balance = D(0)
                        self.payments_for_future = abs(
                            advance_balance_overall_remaining_diff
                        )

                elif self.advance_balance < D(0) and self.interest_payable_balance == D(
                    0
                ):
                    self.payments_for_future = abs(self.advance_balance)
                    self.advance_balance = D(0)

                # We have to charge the interests of today
                if increase_interest:
                    self.interest_payable_balance += self.daily_interest

        # This block of code is reached when there's overall_advance_balance = 0
        # So, if a payment event is found we just add it to payments_for_future.
        # 3. If all advances are repaid, remaining amount goes for future advances
        elif self.interest_payable_balance == D(0):
            remaining_amount = current_event.amount
            self._decrease_oldest_active_balance(remaining_amount)

        # We did something wrong
        elif self.interest_payable_balance < D(0):
            raise ValueError(
                f"overall_interest_patable_balance can not be negative: {self.interest_payable_balance}"
            )

    def _create_advance(self, event, update_balance: bool = True):
        """Creates an advance.

        Notes:
        -----
          - If we have money available in the self.payments_for_future attribute, we want to take it into
            account to decrease the current event amount. Keep in mind that you can create this advance
            and it can be fully paid becase of the amount of money we have available in self.payments_for_future,
            that is if 'advance_payments_for_future_difference' > D(0) or 'advance_payments_for_future_difference' < D(0)

        """
        self.advance_count += 1
        event_amount = event.amount
        is_paid = False

        if self.payments_for_future > 0:
            # How much money does the customer available for the next advance
            advance_payments_for_future_difference = (
                event.amount - self.payments_for_future
            )

            # We pay a portion of the advance
            if advance_payments_for_future_difference > D(0):
                event_amount = advance_payments_for_future_difference
                self.payments_for_future = D(0)
            # We paid all the advance
            elif advance_payments_for_future_difference == D(0):
                event_amount = D(0)
                self.payments_for_future = D(0)
            # We paid the advance and we can store more money in the self.payments_for_future variable.
            elif advance_payments_for_future_difference < D(0):
                event_amount = D(0)
                self.payments_for_future = abs(advance_payments_for_future_difference)

        if event.state and event.state == self.EVENT_TRUNCATED_TYPE:
            pass
        else:
            self.advances[self.advance_count] = {
                "Date": event.date,
                "Initial Amt": event.amount,
                "Current Balance": event_amount,
                "is_paid": is_paid,
            }

        if update_balance:
            self.advance_balance += event_amount

    def process_event(
        self,
        event: Event,
        next_event: Event,
    ):
        """Process an loan or payment event

        Notes:
        ------
          1. We store the last advance balance summary (In case we want to rollback)
          2. If current event date and next event date are equals we just perform the event
             (Create the advance or Excute the payment)
          3. This step is basically the same as before but we calculate the accrued interest
             from event date to next event date and that result is added to the
             self.interest_payable_balance.
        """

        # Store last advance balance summary, that is before we process the following event
        self.last_advance_balance = self.advance_balance
        self.last_interest_payable_balance = self.interest_payable_balance
        self.last_interest_paid = self.interest_paid
        self.last_payments_for_future = self.payments_for_future

        # Current Event Date == Next Event Date
        if event.date == next_event.date:
            next_event.is_same_date = True
            if event.type == self.EVENT_ADVANCE_TYPE:
                self._create_advance(event)
            elif event.type == self.EVENT_PAYMENT_TYPE:
                self._execute_payment_flow(event, increase_interest=False)

        # Current Event Date != Next Event Date
        elif event.date != next_event.date:
            # Event = Advance, Next_Event = Advance
            if event.type == self.EVENT_ADVANCE_TYPE:
                self._create_advance(event)
                if event.is_same_date:
                    if self.advance_balance < D(0):
                        self.payments_for_future += abs(self.advance_balance)
                        self.advance_balance = D(0)

                self.interest_payable_balance += self.get_accrued_interests(
                    next_event.date, event.date, inclusive=True
                )
                self.last_advance = event

            # Event = Payment, Next Event = Advance
            elif event.type == self.EVENT_PAYMENT_TYPE:
                self._execute_payment_flow(
                    event, increase_interest=False
                )  # This carge interests of today
                self.interest_payable_balance += self.get_accrued_interests(
                    next_event.date, event.date, inclusive=True
                )

        self.last_event = event

    def _get_future_event(
        self, events: list, future_event_count: int
    ) -> Union[None, Event]:
        try:
            future_event = Event(*events[future_event_count])
        except IndexError:
            future_event = None
        return future_event

    def get_advance_statistics(
        self,
        events: Iterable[Tuple[int, str, int, str]],
        end_date: date,
    ) -> Tuple[D, D, D, D]:
        """Return the summary of the revolving line of credit, that is returning information
        of the 'overall_advance_balance', 'overall_interest_payable_balance', 'overall_interest_paid' and
        'overall_payments_for_future'.

        Notes:
        ------
          - The strategy chosen is to always look the current_event and the next_event and
            then we proccess the current event. The 'self.process_events' decides what to do.
          - The happy path is when the end_date matches the last event of the events iterable,
            in this case we process the penultimate event within the while loop, the last_event is
            processed out of this loop.
          - There is case when end_date is greater than the last_event, in this case we just also
            process al the events normally, the last_event is executed out of while loop but the
            difference is that we also calculate the accrued interests until the end_date.
          - What do we do when end_date is in-between the events list?
              1. Within the main while loop we just detect if we reached end_date, and we break the
                 execution of the while.
              2. Then we want to see if the event date is different to the next_event date
                 (next_event.date not touches end_date), if that is true, we just process the events normally.
              3. If they (event.date, next_event.date) are equal we may want 'iteratively' to look for a
                 following event of the next_event (we call it future event) because there could
                 be one or several events with the same end_date.

                 We just basically continue to process events until we find two events that are differents
                 (end_date surpassed), then we break the execution and process the last_event.
        """
        total_events = len(events) - 1
        end_date = convert_string_to_date(end_date)
        event_count = 0
        next_event = None
        is_end_date_detected = False

        while event_count < (total_events) and not getattr(
            next_event, "is_last", False
        ):
            next_event_count = event_count + 1

            event = Event(*events[event_count])

            if event.date > end_date:
                return D(0), D(0), D(0), D(0)

            if getattr(next_event, "is_same_date", False):
                event.is_same_date = True

            next_event = Event(*events[next_event_count])

            if next_event_count == total_events:
                next_event.is_last = True
            elif event.date < end_date and end_date <= next_event.date:
                next_event.is_last = True
                is_end_date_detected = True
                break

            self.process_event(event, next_event)
            event_count += 1

        # Logic when end_date is detected and is pointing in-between the events list.
        if is_end_date_detected:
            if end_date == next_event.date:
                future_event_count = event_count + 2
                future_event_exists = True
                while future_event_exists:
                    future_event = self._get_future_event(events, future_event_count)

                    if future_event is None:
                        next_event.is_last = True
                        next_event.date = end_date
                        self.process_event(event, next_event)
                        future_event_exists = False  # breaks the while
                    elif future_event is not None:
                        if next_event.date != future_event.date:
                            next_event.date = end_date
                            self.process_event(event, next_event)
                            future_event_exists = False  # breaks the while
                        elif next_event.date == future_event.date:
                            next_event.is_last = False
                            self.process_event(event, next_event)

                            event_count += 1
                            next_event_count += 1
                            future_event_count += 1

                            event = Event(*events[event_count])
                            next_event = Event(*events[next_event_count])
            else:
                next_event.date = end_date
                next_event.amount = D(0)
                self.process_event(event, next_event)
                next_event.state = self.EVENT_TRUNCATED_TYPE

        last_event = next_event
        if last_event.date == end_date:
            if last_event.type == self.EVENT_ADVANCE_TYPE:
                self._create_advance(next_event)
                self.interest_payable_balance += self.daily_interest
            elif last_event.type == self.EVENT_PAYMENT_TYPE:
                self._execute_payment_flow(last_event, increase_interest=False)
                self.interest_payable_balance += self.daily_interest

        elif end_date > last_event.date:
            if last_event.type == self.EVENT_ADVANCE_TYPE:
                self._create_advance(next_event)
            elif last_event.type == self.EVENT_PAYMENT_TYPE:
                self._execute_payment_flow(last_event, increase_interest=False)
            self.interest_payable_balance += self.daily_interest
            self.interest_payable_balance += self.get_accrued_interests(
                end_date, last_event.date, inclusive=True
            )

        return (
            abs(self.advance_balance),
            abs(self.interest_payable_balance),
            abs(self.interest_paid),
            abs(self.payments_for_future),
        )
