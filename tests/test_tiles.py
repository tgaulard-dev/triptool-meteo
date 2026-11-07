"""Tests du format .ttwx : python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ttwx.tiles import MISSING, Variable, decode_tile, encode_tile, tile_name, tile_origin  # noqa: E402


class TileTests(unittest.TestCase):
    def test_round_trip(self):
        variables = [Variable("10u", "m s-1", 0.01, 0.0), Variable("2t", "K", 0.01, 273.15)]
        rng = np.random.default_rng(1)
        physical = np.stack([rng.uniform(-30, 30, (3, 4, 5)), rng.uniform(240, 320, (3, 4, 5))])
        physical[0, 1, 2, 3] = np.nan
        raw = np.stack([v.quantize(physical[i]) for i, v in enumerate(variables)])
        blob = encode_tile(model="ecmwf", run="2026-11-07T00:00:00Z", steps=[0, 3, 6],
                           variables=variables, lat0=45.0, lon0=-5.0, dlat=0.25, dlon=0.25, data=raw)
        header, values = decode_tile(blob)
        self.assertEqual(header["grid"]["nlat"], 4)
        self.assertEqual(header["grid"]["nlon"], 5)
        self.assertTrue(np.isnan(values[0, 1, 2, 3]))
        self.assertEqual(raw[0, 1, 2, 3], MISSING)
        error = np.nanmax(np.abs(values - physical))
        self.assertLessEqual(error, 0.005 + 1e-9)

    def test_packing_is_lossless(self):
        from ttwx.tiles import pack_values, unpack_values

        rng = np.random.default_rng(2)
        data = rng.integers(-32768, 32768, size=(2, 3, 4, 7)).astype("<i2")
        data[0, 0, 0, :] = MISSING
        data[1, 2, 3, 0] = 32767
        restored = unpack_values(pack_values(data), data.shape)
        self.assertTrue(np.array_equal(restored, data))

    def test_out_of_range_is_missing(self):
        variable = Variable("tp", "m", 0.0001, 0.0)
        self.assertEqual(variable.quantize(np.array([5.0]))[0], MISSING)

    def test_tile_names(self):
        self.assertEqual(tile_name(45, -5), "N45W005")
        self.assertEqual(tile_name(-5, 0), "S05E000")
        self.assertEqual(tile_name(0, -180), "N00W180")
        self.assertEqual(tile_origin(48.07, -4.67), (45, -5))
        self.assertEqual(tile_origin(90.0, 179.75), (85, 175))
        self.assertEqual(tile_origin(-0.25, -0.25), (-5, -5))


if __name__ == "__main__":
    unittest.main()
