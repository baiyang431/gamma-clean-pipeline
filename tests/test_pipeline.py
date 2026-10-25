import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gamma_clean.core import CErr, clnd, lcfg, xct


RT = Path(__file__).resolve().parents[1]
EX = RT / "examples"


class PT(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wd = Path(self.tmp.name)
        self.cfgb = (EX / "schema.json").read_bytes()
        self.cfg = lcfg(self.cfgb)

    def crws(self, rws, cfg=None):
        sio = io.StringIO(newline="")
        wrt = csv.writer(sio, lineterminator="\n")
        wrt.writerows(rws)
        return clnd(sio.getvalue().encode("utf-8"), cfg or self.cfg)

    def scfg(self, cols, **ext):
        cfg = {"version": 1, "columns": cols, **ext}
        return lcfg(json.dumps(cfg).encode())

    def cli(self, *ext, src=None, cfg=None, dst=None):
        return subprocess.run(
            [
                sys.executable, "-m", "gamma_clean",
                "--input", str(src or EX / "dirty.csv"),
                "--schema", str(cfg or EX / "schema.json"),
                "--output-dir", str(dst or self.wd / "result"),
                *ext,
            ],
            cwd=RT, capture_output=True, text=True, encoding="utf-8",
        )

    def test_smp(self):
        clnb, rej, rpt = clnd(
            (EX / "dirty.csv").read_bytes(), self.cfg
        )
        self.assertEqual(clnb, (EX / "expected" / "clean.csv").read_bytes())
        recs = [json.loads(ln) for ln in rej.decode().splitlines()]
        self.assertEqual(
            {rec["record"]: rec["reasons"] for rec in recs},
            {
                3: ["duplicate"],
                5: ["age:below_min"],
                6: ["amount:invalid_number"],
                7: ["joined:invalid_date"],
                8: ["status:not_in_choices"],
                9: ["name:missing_required"],
                11: ["age:above_max"],
            },
        )
        self.assertEqual(
            (
                rpt["input_rows"], rpt["output_rows"], rpt["invalid_rows"],
                rpt["duplicate_rows"], rpt["filled_cells_in_output"],
            ),
            (11, 4, 6, 1, 2),
        )

    def test_idem(self):
        a, _, _ = clnd((EX / "dirty.csv").read_bytes(), self.cfg)
        b, rejb, rpt = clnd(a, self.cfg)
        self.assertEqual(a, b)
        self.assertEqual(rejb, b"")
        self.assertEqual(rpt["filled_cells_in_output"], 0)

    def test_bom(self):
        buf = (EX / "dirty.csv").read_bytes()
        self.assertEqual(
            clnd(b"\xef\xbb\xbf" + buf, self.cfg)[0],
            clnd(buf, self.cfg)[0],
        )

    def test_gb(self):
        buf = (EX / "dirty.csv").read_text(encoding="utf-8").encode("gb18030")
        self.assertEqual(
            clnd(buf, self.cfg, "gb18030")[0],
            (EX / "expected" / "clean.csv").read_bytes(),
        )

    def test_encerr(self):
        buf = (EX / "dirty.csv").read_text(encoding="utf-8").encode("gb18030")
        for cdg in ("utf-8-sig", "does-not-exist"):
            with self.subTest(encoding=cdg), self.assertRaises(CErr):
                clnd(buf, self.cfg, cdg)

    def test_hdr0(self):
        with self.assertRaises(CErr):
            clnd(b"", self.cfg)
        hdr = b"id,name,age,city,amount,joined,status\n"
        clnb, rejb, rpt = clnd(hdr, self.cfg)
        self.assertEqual(clnb, hdr)
        self.assertEqual(rejb, b"")
        self.assertEqual(rpt["input_rows"], 0)

    def test_hdrerr(self):
        for hdr in (
            "id", "id,name,age,city,amount,joined,status,extra",
            "id,name,age,city,amount,joined,id",
        ):
            with self.subTest(header=hdr), self.assertRaises(CErr):
                clnd((hdr + "\n").encode(), self.cfg)
        cfg = self.scfg([{"name": "é", "type": "string"}])
        with self.assertRaises(CErr):
            clnd("e\u0301\nvalue\n".encode("utf-8"), cfg)

    def test_hord(self):
        cfg = self.scfg([
            {"name": "id", "type": "string"}, {"name": "n", "type": "integer"},
        ])
        self.assertEqual(clnd(b"n,id\n02,001\n", cfg)[0], b"id,n\n001,2\n")

    def test_csverr(self):
        cfg = self.scfg([{"name": "id", "type": "string"}])
        for buf in (b'id\n"unterminated\n', b"id\na,b\n", b"id\n\n"):
            with self.subTest(raw=buf), self.assertRaises(CErr):
                clnd(buf, cfg)

    def test_qcsv(self):
        cfg = self.scfg([{"name": "text", "type": "string"}])
        clnb, rejb, _ = self.crws(
            [["text"], ["line 1, hello\nline 2"]], cfg
        )
        self.assertEqual(
            list(csv.reader(io.StringIO(clnb.decode(), newline="")))[1],
            ["line 1, hello\nline 2"],
        )
        self.assertEqual(rejb, b"")

    def test_msv(self):
        cfg = self.scfg([
            {"name": "id", "type": "string"},
            {"name": "a", "type": "integer", "required": False},
            {"name": "b", "type": "string", "required": False, "default": "未知"},
        ])
        clnb, rej, rpt = self.crws(
            [["id", "a", "b"], ["001", "NA", "NULL"], [" ", "", ""]], cfg
        )
        self.assertIn("001,,未知\n", clnb.decode())
        self.assertIn("id:missing_required", rej.decode())
        self.assertEqual(rpt["filled_cells_in_output"], 1)

    def test_dec(self):
        cfg = self.scfg([
            {"name": "n", "type": "number", "min": 0, "max": 100},
        ])
        clnb, rej, rpt = self.crws(
            [["n"], ["0.123456789012345678901234567890"], ["-0.000"], ["100.00"],
             ["100.01"], ["-0.01"], ["NaN"], ["Infinity"], ["1e2"]], cfg,
        )
        self.assertEqual(clnb.decode(), "n\n0.12345678901234567890123456789\n0\n100\n")
        self.assertEqual(rpt["invalid_rows"], 5)
        self.assertIn("above_max", rej.decode())

    def test_int(self):
        cfg = self.scfg([
            {"name": "n", "type": "integer", "min": 0, "max": 120},
        ])
        clnb, _, rpt = self.crws(
            [["n"], ["+000"], ["120"], ["121"], ["1.0"], ["١"]], cfg
        )
        self.assertEqual(clnb, b"n\n0\n120\n")
        self.assertEqual(rpt["invalid_rows"], 3)

    def test_dt(self):
        cfg = self.scfg([{"name": "d", "type": "date"}])
        clnb, _, rpt = self.crws(
            [["d"], ["2024-02-29"], ["2023-02-29"],
             ["2024-2-29"], ["2024/02/29"]], cfg,
        )
        self.assertEqual(clnb, b"d\n2024-02-29\n")
        self.assertEqual(rpt["invalid_rows"], 3)

    def test_dkey(self):
        cfg = self.scfg(
            [{"name": "id", "type": "string"}, {"name": "n", "type": "integer"}],
            dedupe_key=["id"],
        )
        clnb, rej, rpt = self.crws(
            [["id", "n"], ["x", "bad"], ["x", "001"], ["x", "2"]], cfg
        )
        self.assertEqual(clnb, b"id,n\nx,1\n")
        self.assertEqual((rpt["invalid_rows"], rpt["duplicate_rows"]), (1, 1))
        self.assertEqual(
            [json.loads(rec)["record"] for rec in rej.splitlines()],
            [2, 4],
        )

    def test_drow(self):
        cfg = self.scfg([{"name": "n", "type": "integer"}])
        clnb, _, rpt = clnd(b"n\n001\n1\n2\n", cfg)
        self.assertEqual(clnb, b"n\n1\n2\n")
        self.assertEqual(rpt["duplicate_rows"], 1)

    def test_nfckey(self):
        cfg = self.scfg(
            [{"name": "id", "type": "string"}, {"name": "label", "type": "string"}],
            dedupe_key=["id"],
        )
        clnb, rej, rpt = self.crws(
            [
                ["id", "label"], [" e\u0301 ", " first "],
                ["é", "second"], [" é ", "third"],
            ],
            cfg,
        )
        self.assertEqual(clnb.decode(), "id,label\né,first\n")
        self.assertEqual(rpt["duplicate_rows"], 2)
        recs = [json.loads(ln) for ln in rej.splitlines()]
        self.assertEqual(recs[1]["values"], [" é ", "third"])
        self.assertEqual(recs[0]["reasons"], ["duplicate"])

    def test_nfccfg(self):
        cfg = self.scfg(
            [
                {
                    "name": "city", "type": "string", "required": False,
                    "default": " cafe\u0301 ",
                },
                {"name": "status", "type": "string", "choices": [" e\u0301 "]},
            ],
            missing_tokens=["", " N/A "],
        )
        clnb, rej, rpt = self.crws(
            [["city", "status"], ["N/A", "é"], ["cafe\u0301", " e\u0301 "]],
            cfg,
        )
        self.assertEqual(clnb.decode(), "city,status\ncafé,é\n")
        self.assertEqual(rpt["filled_cells_in_output"], 1)
        self.assertEqual(rpt["duplicate_rows"], 1)
        self.assertEqual(json.loads(rej)["reasons"], ["duplicate"])

    def test_nul(self):
        with self.assertRaises(CErr):
            clnd(b"id\x00\n", self.cfg)

    def test_cfgerr(self):
        vld = {"version": 1, "columns": [{"name": "n", "type": "integer"}]}
        bcfgs = [
            [], {}, {**vld, "version": True}, {**vld, "typo": 1},
            {**vld, "dedupe_key": ["absent"]}, {**vld, "dedupe_key": []},
            {**vld, "missing_tokens": ["NA"]},
        ]
        brls = [
            {"name": "n", "type": "imaginary"},
            {"name": "n", "type": "integer", "min": True},
            {"name": "n", "type": "integer", "min": 5, "max": 1},
            {"name": "n", "type": "integer", "required": "yes"},
            {"name": "n", "type": "integer", "required": False, "default": "bad"},
            {"name": "n", "type": "string", "choices": ["a", 1]},
            {"name": " n", "type": "string"},
            {"name": "n", "type": "string", "typo": 1},
        ]
        bcfgs += [{**vld, "columns": [rl]} for rl in brls]
        bcfgs += [{**vld, "columns": vld["columns"] * 2}]
        for cfg in bcfgs:
            with self.subTest(schema=cfg), self.assertRaises(CErr):
                lcfg(json.dumps(cfg).encode())

    def test_jsonerr(self):
        invs = [b'{"version":NaN}', b'{broken', b"\xff"]
        for val in (float("nan"), float("inf"), float("-inf")):
            invs.append(json.dumps({
                "version": 1,
                "columns": [{"name": "n", "type": "number", "min": val}],
            }).encode())
        for buf in invs:
            with self.subTest(raw=buf), self.assertRaises(CErr):
                lcfg(buf)

    def test_cli(self):
        res = self.cli()
        self.assertEqual(res.returncode, 0, res.stderr)
        dst = self.wd / "result"
        self.assertEqual(
            {pth.name for pth in dst.iterdir()},
            {"clean.csv", "rejected.jsonl", "report.json"},
        )
        rpt = json.loads((dst / "report.json").read_bytes())
        self.assertEqual(
            rpt["input_rows"], rpt["output_rows"] + rpt["rejected_rows"]
        )
        self.assertEqual(
            (dst / "clean.csv").read_bytes(),
            (EX / "expected" / "clean.csv").read_bytes(),
        )
        recs = (dst / "rejected.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(recs), rpt["rejected_rows"])

    def test_sterr(self):
        res = self.cli("--strict")
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("Strict mode", res.stderr)
        self.assertFalse((self.wd / "result").exists())

    def test_st(self):
        res = self.cli("--strict", src=EX / "expected" / "clean.csv")
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_rc2(self):
        ivf = self.wd / "bad.json"
        ivf.write_text("{}", encoding="utf-8")
        rs = [self.cli(cfg=ivf), self.cli("--encoding", "absent")]
        for res in rs:
            self.assertEqual(res.returncode, 2, res.stderr)
            self.assertFalse((self.wd / "result").exists())

    def test_rc3(self):
        res = self.cli(src=self.wd / "missing.csv")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertFalse((self.wd / "result").exists())

    def test_od(self):
        dst = self.wd / "result"
        dst.mkdir()
        (dst / "marker").write_bytes(b"keep me")
        res = self.cli()
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertEqual(list(dst.iterdir()), [dst / "marker"])
        self.assertEqual((dst / "marker").read_bytes(), b"keep me")

    def test_fmt(self):
        ivf = self.wd / "bad.csv"
        ivf.write_bytes(b"wrong,header\n")
        res = self.cli(src=ivf)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertFalse((self.wd / "result").exists())
        self.assertFalse(list(self.wd.glob(".gamma-clean-*")))

    def test_pth(self):
        src = self.wd / "source with spaces.csv"
        buf = (EX / "dirty.csv").read_bytes()
        src.write_bytes(buf)
        res = self.cli(src=src, dst=self.wd / "result with spaces")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(src.read_bytes(), buf)
        self.assertEqual((EX / "schema.json").read_bytes(), self.cfgb)

    def test_wrerr(self):
        ow = Path.write_bytes

        def werr(pth, dat):
            if pth.name == "report.json":
                raise OSError("simulated disk error")
            return ow(pth, dat)

        with patch("gamma_clean.core.Path.write_bytes", new=werr):
            with self.assertRaises(OSError):
                xct(
                    EX / "dirty.csv", EX / "schema.json",
                    self.wd / "result",
                )
        self.assertFalse((self.wd / "result").exists())
        self.assertFalse(list(self.wd.glob(".gamma-clean-*")))

    def test_args(self):
        res = subprocess.run(
            [sys.executable, "-m", "gamma_clean"], cwd=RT, capture_output=True
        )
        self.assertEqual(res.returncode, 2)
        res = subprocess.run(
            [sys.executable, "-m", "gamma_clean", "--version"],
            cwd=RT, capture_output=True, text=True,
        )
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "1.0.0"))


if __name__ == "__main__":
    unittest.main()
