"""Host-only reference solution for the cobol-modernization conversion.

This is qualification material, not scoring logic and not a public asset. It is
never mounted into an Agent or Evaluation environment; the focused test copies it
into a throwaway workspace to prove gate 2 (reference success).

It is a faithful Python port of the pinned source program at
``benchmarks/terminal-bench/docker/cobol-modernization/src/program.cbl``
(PROGRAM-ID. BOOKFORUM), reproducing the record layouts, validation order, and
mutation behavior of the original.

Record layouts, from the COBOL FILE SECTION:

    ACCOUNT-RECORD      ID X(4)  NAME X(20)  BALANCE 9(10)   -> 34 bytes
    BOOK-RECORD         ID X(4)  TITLE X(20) OWNER X(4)      -> 28 bytes
    TRANSACTION-RECORD  BOOK X(4) AMOUNT 9(10) SELLER X(4) BUYER X(4) -> 22 bytes
    INPUT-RECORD        BUYER X(4) SELLER X(4) BOOK X(4) AMOUNT 9(10) -> 22 bytes

The files are unterminated fixed-width streams with no record separators.
"""

from __future__ import annotations

from pathlib import Path


ACCOUNT_RECORD_BYTES = 34
BOOK_RECORD_BYTES = 28
INPUT_RECORD_BYTES = 22

DATA_DIR = Path("data")
ACCOUNTS_PATH = DATA_DIR / "ACCOUNTS.DAT"
BOOKS_PATH = DATA_DIR / "BOOKS.DAT"
TRANSACTIONS_PATH = DATA_DIR / "TRANSACTIONS.DAT"
INPUT_PATH = Path("src") / "INPUT.DAT"


def _split_records(text: str, width: int) -> list[str]:
    """Split a fixed-width stream, ignoring a short trailing remainder.

    GnuCOBOL's sequential READ reaches AT END rather than yielding a partial
    record, so a trailing fragment contributes nothing.
    """

    return [
        text[start : start + width]
        for start in range(0, len(text) - width + 1, width)
    ]


def main() -> None:
    # MAIN-PARA: read one input record, or report an empty input file.
    raw_input_record = INPUT_PATH.read_text(encoding="utf-8")
    if len(raw_input_record) < INPUT_RECORD_BYTES:
        # COBOL: DISPLAY "Error: Input file is empty" / STOP RUN.
        print("Error: Input file is empty")
        return

    buyer_id = raw_input_record[0:4]
    seller_id = raw_input_record[4:8]
    book_id = raw_input_record[8:12]
    amount = int(raw_input_record[12:22])

    accounts = _split_records(
        ACCOUNTS_PATH.read_text(encoding="utf-8"), ACCOUNT_RECORD_BYTES
    )
    books = _split_records(BOOKS_PATH.read_text(encoding="utf-8"), BOOK_RECORD_BYTES)

    # VALIDATE-USERS-AND-BOOK.
    buyer_found = any(record[0:4] == buyer_id for record in accounts)
    seller_found = any(record[0:4] == seller_id for record in accounts)
    book_found = False
    valid_owner = False
    for record in books:
        if record[0:4] == book_id:
            book_found = True
            if record[24:28] == seller_id:
                valid_owner = True
    print(" ")

    if not (buyer_found and seller_found and book_found and valid_owner):
        print("Transaction failed due to validation errors")
        return

    # PROCESS-TRANSACTION: rewrite matching account records in place, preserving
    # file order and every non-matching record byte-for-byte.
    updated_accounts: list[str] = []
    for record in accounts:
        account_id = record[0:4]
        name = record[4:24]
        balance = int(record[24:34])
        if account_id == buyer_id:
            balance -= amount
        if account_id == seller_id:
            balance += amount
        updated_accounts.append(f"{account_id}{name}{balance:010d}")

    updated_books: list[str] = []
    for record in books:
        if record[0:4] == book_id:
            updated_books.append(f"{record[0:4]}{record[4:24]}{buyer_id}")
        else:
            updated_books.append(record)

    ACCOUNTS_PATH.write_text("".join(updated_accounts), encoding="utf-8")
    BOOKS_PATH.write_text("".join(updated_books), encoding="utf-8")

    # OPEN EXTEND TRANSACTIONS-FILE / WRITE TRANSACTION-RECORD.
    with TRANSACTIONS_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"{book_id}{amount:010d}{seller_id}{buyer_id}")

    print("Transaction completed successfully")


if __name__ == "__main__":
    main()
