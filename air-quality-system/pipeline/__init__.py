"""Integration contracts for the three independently owned HW tickets."""


class WaitingForData(Exception):
    """HW-01/HW-02 may raise this while collecting sufficient fresh history."""
