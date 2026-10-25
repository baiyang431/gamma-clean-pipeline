import codecs
import csv
import io
import json
import re
import tempfile
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import __version__


class CErr(Exception):
    """携带命令行退出码的清洗错误。"""

    def __init__(self, msg, rc=2):
        super().__init__(msg)
        self.rc = rc


def nfc(val):
    return unicodedata.normalize("NFC", val).strip()


def cvt(val, rl):
    """校验失败时抛出 ValueError，错误消息直接用作剔除原因。"""
    typ = rl["type"]
    if typ == "integer":
        if not re.fullmatch(r"[+-]?[0-9]+", val):
            raise ValueError("invalid_integer")
        try:
            val = str(int(val))
        except ValueError:
            raise ValueError("invalid_integer") from None
        num = Decimal(val)
    elif typ == "number":
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", val):
            raise ValueError("invalid_number")
        num = Decimal(val)
        val = format(num, "f")
        if "." in val:
            val = val.rstrip("0").rstrip(".")
        if num == 0:
            val = "0"
    elif typ == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", val):
            raise ValueError("invalid_date")
        try:
            val = date.fromisoformat(val).isoformat()
        except ValueError:
            raise ValueError("invalid_date") from None
    if typ in ("integer", "number"):
        if "min" in rl and num < Decimal(str(rl["min"])):
            raise ValueError("below_min")
        if "max" in rl and num > Decimal(str(rl["max"])):
            raise ValueError("above_max")
    if "choices" in rl and val not in rl["choices"]:
        raise ValueError("not_in_choices")
    return val


def lcfg(buf):
    try:
        cfg = json.loads(buf.decode("utf-8-sig"))
    except ValueError as err:
        raise CErr(f"Invalid schema JSON: {err}") from err
    aks = {"version", "columns", "dedupe_key", "missing_tokens"}
    if not isinstance(cfg, dict) or set(cfg) - aks:
        raise CErr("Schema must be an object with only supported keys")
    if type(cfg.get("version")) is not int or cfg["version"] != 1:
        raise CErr("Schema version must be integer 1")
    cols = cfg.get("columns")
    if not isinstance(cols, list) or not cols:
        raise CErr("Schema columns must be a nonempty list")
    tks = cfg.setdefault("missing_tokens", ["", "NA", "N/A", "NULL", "null"])
    if (
        not isinstance(tks, list)
        or not all(isinstance(tk, str) for tk in tks)
        or "" not in tks
    ):
        raise CErr("missing_tokens must be a string list containing empty string")
    tks = [nfc(tk) for tk in tks]
    cfg["missing_tokens"] = tks
    nms = []
    cks = {"name", "type", "required", "default", "min", "max", "choices"}
    for rl in cols:
        if not isinstance(rl, dict) or set(rl) - cks:
            raise CErr("Column rule contains unsupported keys")
        nm = rl.get("name")
        if (
            not isinstance(nm, str)
            or not nm
            or nm.strip() != nm
            or nm in nms
        ):
            raise CErr("Column names must be nonempty, trimmed, and unique")
        nms.append(nm)
        if rl.get("type") not in ("string", "integer", "number", "date"):
            raise CErr(f"Unsupported type for {nm}")
        if type(rl.setdefault("required", True)) is not bool:
            raise CErr(f"required must be boolean: {nm}")
        for bnd in ("min", "max"):
            if bnd in rl:
                val = rl[bnd]
                if (
                    rl["type"] not in ("integer", "number")
                    or type(val) not in (int, float)
                    or not Decimal(str(val)).is_finite()
                ):
                    raise CErr(f"Invalid numeric bound: {nm}.{bnd}")
        if "min" in rl and "max" in rl and rl["min"] > rl["max"]:
            raise CErr(f"min exceeds max: {nm}")
        if "choices" in rl:
            opts = rl["choices"]
            if (
                rl["type"] != "string"
                or not isinstance(opts, list)
                or not opts
                or not all(isinstance(opt, str) for opt in opts)
            ):
                raise CErr(f"choices must be a nonempty string list: {nm}")
            rl["choices"] = [nfc(opt) for opt in opts]
        if "default" in rl:
            val = rl["default"]
            if rl["required"] or not isinstance(val, str):
                raise CErr(f"default needs an optional string value: {nm}")
            val = nfc(val)
            if val in tks:
                raise CErr(f"default must not be a missing token: {nm}")
            try:
                rl["default"] = cvt(val, rl)
            except ValueError as err:
                raise CErr(f"Invalid default for {nm}: {err}") from err
    ks = cfg.setdefault("dedupe_key", nms)
    if (
        not isinstance(ks, list)
        or not ks
        or not all(isinstance(k, str) and k in nms for k in ks)
        or len(set(ks)) != len(ks)
    ):
        raise CErr("dedupe_key must contain unique existing column names")
    return cfg


def clnr(rw, cols, cix, mts):
    cln = []
    errs = []
    nf = 0
    for rl, idx in zip(cols, cix):
        val = nfc(rw[idx])
        if val in mts:
            if "default" in rl:
                val = rl["default"]
                nf += 1
            elif rl["required"]:
                errs.append(f"{rl['name']}:missing_required")
            else:
                val = ""
        else:
            try:
                val = cvt(val, rl)
            except ValueError as err:
                errs.append(f"{rl['name']}:{err}")
        cln.append(val)
    return cln, errs, nf


def ser(nms, rws, rej):
    dst = io.StringIO(newline="")
    wrt = csv.writer(dst, lineterminator="\n")
    wrt.writerow(nms)
    wrt.writerows(rws)
    clnb = dst.getvalue().encode("utf-8")
    rejb = "".join(
        json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n"
        for rec in rej
    ).encode("utf-8")
    return clnb, rejb


def clnd(buf, cfg, cdg="utf-8-sig"):
    try:
        enc = codecs.lookup(cdg).name
        txt = buf.decode(cdg, errors="strict")
    except (LookupError, UnicodeError) as err:
        raise CErr(f"Cannot decode input with {cdg}: {err}") from err
    if "\x00" in txt:
        raise CErr("Input contains NUL characters; check encoding or file type")
    csv.field_size_limit(1_000_000)
    rdr = csv.reader(io.StringIO(txt, newline=""), strict=True)
    cols = cfg["columns"]
    nms = [rl["name"] for rl in cols]
    crws = []
    rej = []
    sks = set()
    ni = nd = nf = nr = 0
    try:
        hdr = next(rdr, None)
        if hdr is None or len(hdr) != len(nms) or set(hdr) != set(nms):
            raise CErr("CSV header must contain each schema column exactly once")
        cix = [hdr.index(nm) for nm in nms]
        kix = [nms.index(nm) for nm in cfg["dedupe_key"]]
        for rec, rw in enumerate(rdr, start=2):
            nr += 1
            if len(rw) != len(hdr):
                raise CErr(
                    f"CSV record {rec}: expected {len(hdr)} cells, got {len(rw)}"
                )
            cln, errs, nfl = clnr(
                rw, cols, cix, cfg["missing_tokens"]
            )
            if errs:
                ni += 1
            else:
                k = tuple(cln[i] for i in kix)
                if k in sks:
                    nd += 1
                    errs = ["duplicate"]
                else:
                    sks.add(k)
                    crws.append(cln)
                    nf += nfl
            if errs:
                rej.append({"record": rec, "values": rw, "reasons": errs})
    except csv.Error as err:
        raise CErr(
            f"Malformed CSV near physical line {rdr.line_num}: {err}"
        ) from err
    clnb, rejb = ser(nms, crws, rej)
    rpt = {
        "tool_version": __version__,
        "schema_version": cfg["version"],
        "encoding": enc,
        "input_rows": nr,
        "output_rows": len(crws),
        "invalid_rows": ni,
        "duplicate_rows": nd,
        "rejected_rows": len(rej),
        "filled_cells_in_output": nf,
        "dedupe_key": cfg["dedupe_key"],
        "dedupe_policy": "first_valid_record",
    }
    return clnb, rejb, rpt


def xct(ip, cp, od, cdg="utf-8-sig", st=False):
    ip = Path(ip)
    cp = Path(cp)
    od = Path(od)
    if od.exists() or od.is_symlink():
        raise CErr(f"Output directory already exists: {od}", 3)
    cfg = lcfg(cp.read_bytes())
    clnb, rej, rpt = clnd(ip.read_bytes(), cfg, cdg)
    if st and rpt["rejected_rows"]:
        raise CErr(
            f"Strict mode: {rpt['rejected_rows']} rejected records; "
            "no output published",
            1,
        )
    rpt["strict"] = st
    od.parent.mkdir(parents=True, exist_ok=True)
    # 避免写入失败后留下不完整的结果。
    with tempfile.TemporaryDirectory(
        prefix=".gamma-clean-", dir=od.parent
    ) as td:
        tmp = Path(td)
        (tmp / "clean.csv").write_bytes(clnb)
        (tmp / "rejected.jsonl").write_bytes(rej)
        rtxt = json.dumps(rpt, ensure_ascii=False, indent=2, sort_keys=True)
        (tmp / "report.json").write_bytes((rtxt + "\n").encode("utf-8"))
        tmp.rename(od)
    return rpt
