import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from heytap_eq.clipboard import decode_text, tuning_payload
from heytap_eq.correction_range import CorrectionRange
from heytap_eq.dsp import SAMPLE_RATES, correction, filter_response
from heytap_eq.eq_formats import EQDocument, Filter, dump_eq, parse_text
from heytap_eq.firmware_edit import fit_record, metrics
from heytap_eq.session import Session


class CorrectionRangeTests(unittest.TestCase):
    def test_centered_weights_and_independent_widths(self):
        settings = CorrectionRange(True, 100., 8000., 1., 2.)
        np.testing.assert_allclose(settings.weights([50, 100/2**.5, 100, 100*2**.5,
                                                    4000, 8000, 16000, 20000]),
                                   [0, 0, .5, 1, 1, .5, 0, 0], atol=1e-12)
        settings.high_octaves = 1/3
        np.testing.assert_allclose(settings.weights([70, 100, 150]), [0, .5, 1], atol=1e-12)
        # Smooth attachment: both slope and curvature approach zero at the outer edge.
        edge = settings.low_hz/2**.5
        value = settings.weights(edge*2**np.array([0., 1e-4, 2e-4]))
        self.assertLess(value[1], 2e-11)
        self.assertLess(abs(value[2]-2*value[1]), 7e-11)

    def test_narrow_range_keeps_width_ratio_and_requested_values(self):
        settings = CorrectionRange(True, 7900, 8000, 2., .5)
        low, high = settings.widths()
        self.assertAlmostEqual(low/high, 4.)
        self.assertAlmostEqual((low+high)/2, np.log2(8000/7900))
        np.testing.assert_allclose(settings.weights([7900, 8000]), [.5, .5], atol=1e-12)
        settings.low_hz = 100
        self.assertEqual(settings.widths(), (2., .5))

    def test_disabled_and_full_frequency_preserve_old_response(self):
        doc = EQDocument(raw=[[20., 1.], [20000., -1.]], filters=[Filter(1, 1000., 2., .7)])
        f = np.geomspace(20, 20000, 1024)
        original = np.interp(np.log(f), np.log([20, 20000]), [1, -1])+filter_response(doc.filters, f)
        np.testing.assert_array_equal(correction(doc, f), original)
        doc.correction_range.enabled = True
        np.testing.assert_array_equal(correction(doc, f), original)

    def test_total_response_is_windowed_without_deleting_filters(self):
        doc = EQDocument(raw=[[20., 2.], [20000., 2.]],
                         filters=[Filter(1, 40., 5., .5), Filter(2, 15000., 4., 1.)],
                         correction_range=CorrectionRange(True, 100, 8000))
        original = copy.deepcopy(doc.to_dict())
        frequency = np.geomspace(20, 20000, 4096)
        for rate in SAMPLE_RATES:
            expected = (2+filter_response(doc.filters, frequency, rate))*doc.correction_range.weights(frequency)
            np.testing.assert_array_equal(correction(doc, frequency, rate), expected)
            self.assertTrue(np.all(expected[doc.correction_range.outside(frequency)] == 0))
        self.assertEqual(doc.to_dict(), original)

    def test_effective_raw_export_roundtrip_at_each_rate(self):
        doc = EQDocument(raw=[[20., .2], [1000., -.3], [20000., .2]],
                         filters=[Filter(1, 200, 4, .8), Filter(2, 1000, 12, .5, enabled=False)],
                         correction_range=CorrectionRange(True, 100, 8000, 1/3, 2.))
        frequency = np.geomspace(20, 20000, 8192)
        for rate in SAMPLE_RATES:
            imported = parse_text(dump_eq(doc, rate))
            self.assertEqual(imported.metadata["SAMPLE_RATE_HZ"], str(rate))
            self.assertEqual(imported.metadata["HEYTAP_EFFECTIVE_CORRECTION"], "1")
            self.assertFalse(imported.correction_range.enabled)
            self.assertFalse(imported.filters)
            self.assertLess(np.max(abs(correction(imported, frequency, rate)-correction(doc, frequency, rate))), .003)
            imported_again = parse_text(dump_eq(imported, rate))
            np.testing.assert_array_equal(correction(imported, frequency, rate), correction(imported_again, frequency, rate))
            self.assertTrue(decode_text(dump_eq(doc, rate))["external_eq"])

    def test_project_clipboard_undo_and_legacy_default(self):
        session = Session()
        doc = EQDocument(filters=[Filter(1, 1000, 2, 1)], correction_range=CorrectionRange(True, 100, 8000, .5, 2))
        session.replace(doc)
        payload = json.loads(json.dumps(tuning_payload(session)))
        pasted = Session()
        pasted.paste_tuning(payload["state"])
        self.assertEqual(pasted.document.to_dict(), doc.to_dict())
        session.undo()
        self.assertFalse(session.document.correction_range.enabled)
        session.redo()
        self.assertEqual(session.document.to_dict(), doc.to_dict())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"session.json"
            session.save(path)
            restored = Session()
            restored.restore(path)
            self.assertEqual(restored.document.to_dict(), doc.to_dict())
            saved = json.loads(path.read_text())
            del saved["eq"]["correction_range"]
            path.write_text(json.dumps(saved))
            restored.restore(path)
            self.assertFalse(restored.document.correction_range.enabled)

    def test_firmware_optimizer_and_independent_outside_metrics(self):
        doc = EQDocument(filters=[Filter(1, 1000, 2., 1.)],
                         correction_range=CorrectionRange(True, 100., 8000.))
        record = fit_record({"gain0": -3., "gain1": -3., "count": 0, "slots": []}, doc, max_nfev=35)
        self.assertGreater(record["optimizer_nfev"], 0)
        self.assertLessEqual(len(record["filters"]), 18)
        actual = metrics([], record["filters"], doc)
        self.assertEqual(actual, record["metrics"])
        for value in actual.values():
            self.assertLess(value["outside_max_db"], .2)
            self.assertTrue(value["outside_within_reference"])
            self.assertLess(value["max_db"], .1)
        # Report fields cannot hide an actual change: independent calculation finds it.
        forged = [{"type_id": 0, "gain": 4., "fc": 100., "q": .7}]
        self.assertTrue(any(not value["outside_within_reference"] for value in metrics([], forged, doc).values()))

    def test_invalid_range_values_are_rejected(self):
        for settings in ({"enabled": 1}, {"low_hz": 0}, {"low_hz": 100, "high_hz": 100},
                         {"low_octaves": 0}, {"high_octaves": float("nan")}, {"extra": 1}):
            with self.assertRaises(ValueError):
                CorrectionRange.from_dict(settings)

    def test_transition_extending_beyond_plot_is_not_counted_as_outside(self):
        settings = CorrectionRange(True, 21., 19000., 2., 2.)
        self.assertFalse(np.any(settings.outside(np.geomspace(20, 20000, 1024))))
        self.assertTrue(np.all(settings.weights([20., 20000.]) > 0))
        doc = EQDocument(filters=[Filter(1, 1000, 2, 1)], correction_range=settings)
        value = metrics([], [], doc)["48000"]
        self.assertEqual(value["outside_samples"], 0)
        self.assertIsNone(value["outside_within_reference"])


if __name__ == "__main__":
    unittest.main()
