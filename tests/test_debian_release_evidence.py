import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('system_evidence',Path(__file__).resolve().parents[1]/'scripts/validate-system-evidence.py')
evidence=importlib.util.module_from_spec(spec);spec.loader.exec_module(evidence)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'boot-status').write_text('passed\n')
        self.runtime={'ok':True,'raw_image_unchanged':True,'checks':[{'name':n,'status':'passed'} for n in evidence.RUNTIME]}
        self.ab={'ok':True,'raw_image_unchanged':True,'checks':sorted(evidence.AB)}
    def save(self):
        (self.root/'runtime-test.json').write_text(json.dumps(self.runtime))
        (self.root/'ab-test.json').write_text(json.dumps(self.ab))
    def test_complete_checks_allow_signing(self):
        self.save();self.assertEqual(set(evidence.validate(self.root).values()),{'passed'})
    def test_missing_check_cannot_be_hidden_by_overall_success(self):
        self.runtime['checks'].pop();self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_skipped_required_check_is_not_success(self):
        self.runtime['checks'][0]['status']='skipped';self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_image_mutation_blocks_publication(self):
        self.ab['raw_image_unchanged']=False;self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_missing_fallback_blocks_publication(self):
        self.ab['checks'].remove('failed_candidate_fallback_after_reset');self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_conflicting_duplicate_checks_rejected(self):
        self.runtime['checks'].append({**self.runtime['checks'][0],'status':'failed'});self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
