"""Opening a plan file and the HDF5 paths and byte strings HEC-RAS writes."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator, Sequence
from typing import Any

import h5py
import numpy as np
import pandas as pd

GEOMETRY = "Geometry/2D Flow Areas"
RESULTS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


@contextlib.contextmanager
def open_hdf(path: Any) -> Iterator[h5py.File]:
    """Open a plan file read-only from a ``str``, an ``os.PathLike`` or a binary file object.

    A file object is left open for its owner; a path is closed on exit. A ``UPath`` on a
    share is passed as ``upath.open("rb")``: ``os.fspath`` of a remote ``UPath`` gives a URL that
    h5py cannot open.
    """
    source = path if hasattr(path, "read") else os.fspath(path)
    with h5py.File(source, "r") as file:
        yield file


def decode(value: Any) -> str:
    """Return ``value`` as a stripped ``str``, decoding the byte strings HDF5 holds."""
    if isinstance(value, np.ndarray) and value.shape == ():
        value = value[()]
    if isinstance(value, bytes | np.bytes_):
        # Strict: every attribute and table byte string in the plans checked is UTF-8, so an
        # undecodable one is corruption, not a HEC-RAS habit to paper over.
        return bytes(value).decode("utf-8").strip()
    return str(value).strip()


_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), start=1)}  # fmt: skip


def parse_time_date_stamp(values: Sequence[bytes]) -> pd.DatetimeIndex:
    """Parse HEC-RAS ``Time Date Stamp`` strings, such as ``b"30NOV2016 00:00:00"``.

    HEC-RAS writes the strings fixed-width (``S18`` or ``S19``), so a value may carry trailing
    spaces or NUL bytes. A ``24:00:00`` hour is read as 00:00:00 of the next day. The stamps are
    naive local times: HEC-RAS stores no time zone.
    """
    stamps = [bytes(value).replace(b"\x00", b"").decode("ascii").strip() for value in values]
    next_day = [stamp.endswith(" 24:00:00") for stamp in stamps]
    texts = [stamp.replace(" 24:00:00", " 00:00:00") if late else stamp for stamp, late in
             zip(stamps, next_day, strict=True)]  # fmt: skip
    # %b follows the locale, so HEC-RAS's English abbreviations are mapped to numbers here
    numeric = []
    for text, stamp in zip(texts, stamps, strict=True):
        month = _MONTHS.get(text[2:5].upper())
        if month is None:
            raise ValueError(f"unknown month {text[2:5]!r} in Time Date Stamp {stamp!r}")
        numeric.append(text[:2] + month + text[5:])
    times = pd.to_datetime(numeric, format="%d%m%Y %H:%M:%S")
    return times + pd.to_timedelta(np.array(next_day, dtype="int64"), unit="D")
