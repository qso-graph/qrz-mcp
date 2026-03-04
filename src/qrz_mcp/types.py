"""Typed records for QRZ API responses."""

from __future__ import annotations

from typing import TypedDict


class CallsignRecord(TypedDict, total=False):
    """Structured callsign lookup result from QRZ XML API."""

    call: str
    fname: str
    name: str
    grid: str
    lat: float
    lon: float
    dxcc: int
    country: str
    license_class: str
    email: str
    qslmgr: str
    image: str
    eqsl: bool
    mqsl: bool
    lotw: bool
    cqzone: int
    ituzone: int
    iota: str
    county: str
    state: str
    born: str
    addr1: str
    addr2: str


class DxccRecord(TypedDict, total=False):
    """DXCC entity record from QRZ XML API."""

    dxcc: int
    name: str
    continent: str
    cqzone: int
    ituzone: int
    lat: float
    lon: float
    cc: str  # ISO country code


class LogbookStatus(TypedDict, total=False):
    """Logbook statistics from QRZ Logbook API."""

    callsign: str
    count: int
    confirmed: int
    dxcc: int
    us_states: int
    start_date: str
    end_date: str


class QsoRecord(TypedDict, total=False):
    """Single QSO record from QRZ logbook fetch."""

    logid: str
    call: str
    band: str
    mode: str
    qso_date: str
    time_on: str
    rst_sent: str
    rst_rcvd: str
    gridsquare: str
    comment: str
    qsl_rcvd: str
    qsl_sent: str
    dxcc: int
    country: str
    freq: str
