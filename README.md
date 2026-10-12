# Apartment Booking CLI

A small command-line backend for managing apartments and bookings. Python 3.9+ only, no dependencies.
Data is saved to `./data.json`. You can change the location with `--data PATH` or `APT_DATA_FILE`.

```sh
python3 -m apartment_booking apartment add "Sea View Loft" --address "1 Beach Rd" --rooms 2 --price 120
python3 -m apartment_booking apartment update 1 --price 110
python3 -m apartment_booking apartment view 1
python3 -m apartment_booking apartment list
python3 -m apartment_booking apartment remove 1        # refused while it has active bookings

python3 -m apartment_booking booking create 1 Ann 2026-11-01 2026-11-05
python3 -m apartment_booking booking view 1
python3 -m apartment_booking booking list [--apartment 1] [--guest Ann] [--all]
python3 -m apartment_booking booking change 1 --check-out 2026-11-07 [--apartment 2] [--guest Bob]
python3 -m apartment_booking booking cancel 1

python3 -m apartment_booking search 2026-11-03 2026-11-04 [--min-rooms 2]
```

Add `--json` before the command to get JSON output, e.g. `python3 -m apartment_booking --json apartment list`.

## Rules
- Dates use `YYYY-MM-DD`. The check-in day is included and the check-out day is not, so one guest can check out on the same day the next guest checks in.
- A booking is rejected if it overlaps an active booking for the same apartment. This applies when creating a booking and when changing one. A booking being changed does not count as overlapping with itself.
- Cancelled bookings stay in the history (`--all`) but no longer block their dates.
- Errors print to stderr and the command exits with code 1.

## Tests
```sh
python3 -m unittest -v
```
