# Apartment Booking CLI

Authors: Laurel Matt and Kleidi Gjeta 

> This app was made as an exercise for the course Continuous Integration and Delivery (76106B) at the Free University of Bozen-Bolzano (unibz).

Command-line app for managing apartments and bookings, with availability search and overlap prevention.

Requires Python 3.9+. No dependencies.

```sh
git clone https://github.com/laurelcrelia/apartment_booking.git
cd apartment_booking
python3 booking.py --help
```

## Usage

```
Usage: booking.py COMMAND [OPTIONS]
Commands:
apartment list
apartment view ID
apartment add --name NAME --address ADDRESS [--rooms N] [--price PRICE]
apartment update ID [--name NAME] [--address ADDRESS] [--rooms N] [--price PRICE]
apartment remove ID
apartment search --from DATE --to DATE [--min-rooms N]
booking list [--apartment ID] [--guest NAME] [--all]
booking view ID
booking create --apartment ID --from DATE --to DATE [--guest NAME]
booking change ID [--from DATE] [--to DATE] [--apartment ID] [--guest NAME]
booking cancel ID
```

Example:

```sh
python3 booking.py apartment add --name Loft --address "1 Beach Rd"
python3 booking.py booking create --apartment 1 --from 2026-11-01 --to 2026-11-05
python3 booking.py apartment search --from 2026-11-03 --to 2026-11-04
```

- Dates are `YYYY-MM-DD`. `--to` is the check-out day (exclusive), so back-to-back stays are allowed.
- Overlapping bookings for the same apartment are rejected (exit code 1).
- Cancelled bookings free their dates and are shown only with `--all`.
- Apartments with active bookings can't be removed.
- Add `--json` to any command for JSON output.

## Data

Data is stored in `./data.json`. Override with `--data PATH` or `APT_DATA_FILE`.

## Tests

```sh
python3 -m unittest -v
```
