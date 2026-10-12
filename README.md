# Apartment Booking CLI

Command-line app for managing apartments and bookings, with availability search and overlap prevention.

Requires Python 3.9+. No dependencies.

```sh
git clone https://github.com/laurelcrelia/apartment_booking.git
cd apartment_booking
python3 -m apartment_booking --help
```

## Usage

```sh
python3 -m apartment_booking apartment add "Loft" --address "1 Beach Rd" --rooms 2 --price 120
python3 -m apartment_booking apartment list | view ID | update ID [--name --address --rooms --price] | remove ID

python3 -m apartment_booking booking create APARTMENT_ID GUEST CHECK_IN CHECK_OUT
python3 -m apartment_booking booking list [--apartment ID] [--guest NAME] [--all]
python3 -m apartment_booking booking view ID | cancel ID
python3 -m apartment_booking booking change ID [--apartment --guest --check-in --check-out]

python3 -m apartment_booking search CHECK_IN CHECK_OUT [--min-rooms N]
```

- Dates are `YYYY-MM-DD`. Check-out is exclusive, so back-to-back stays are allowed.
- Overlapping bookings for the same apartment are rejected (exit code 1).
- Cancelled bookings free their dates and are shown only with `--all`.
- Apartments with active bookings can't be removed.
- Add `--json` before the command for JSON output.

## Data

Data is stored in `./data.json`. Override with `--data PATH` or `APT_DATA_FILE`.

## Tests

```sh
python3 -m unittest -v
```
