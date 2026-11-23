#!/usr/bin/env python3
"""Entry point: python booking.py --help"""
import sys

from booking_cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
