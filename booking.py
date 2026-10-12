#!/usr/bin/env python3
"""Entry point: python booking.py --help"""
import sys

from apartment_booking.cli import main

if __name__ == "__main__":
    sys.exit(main())
