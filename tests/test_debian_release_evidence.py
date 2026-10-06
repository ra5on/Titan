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
        next(x for x in self.runtime['checks'] if x['name']=='storage_data_boundary')['values']={name:True for name in evidence.STORAGE_BOUNDARY}
        next(x for x in self.runtime['checks'] if x['name']=='custom_service_containment')['values']={name:True for name in evidence.CONTAINMENT}
        next(x for x in self.runtime['checks'] if x['name']=='storage_components')['values']={**{name:True for name in evidence.STORAGE_COMPONENTS},
            'kernel':'6.12.63+deb13-amd64','zfs_arc_max_bytes':1073741824,'zfs_arc_min_bytes':134217728,'zfs_arc_size_bytes':0}
        self.ab={'ok':True,'raw_image_unchanged':True,'checks':sorted(evidence.AB)+['published_release_baseline'],
                 'baseline_source':'published-release','baseline_version':'0.4.6-alpha.1','baseline_image_unchanged':True}
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
    def test_synthetic_baseline_cannot_publish_update(self):
        self.ab['baseline_source']='synthetic';self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_conflicting_duplicate_checks_rejected(self):
        self.runtime['checks'].append({**self.runtime['checks'][0],'status':'failed'});self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_incomplete_or_nonboolean_storage_boundary_cannot_publish(self):
        boundary=next(x for x in self.runtime['checks'] if x['name']=='storage_data_boundary')
        for field in evidence.STORAGE_BOUNDARY:
            for value in (False,1,'true',None):
                with self.subTest(field=field,value=value):
                    boundary['values']={name:True for name in evidence.STORAGE_BOUNDARY}
                    boundary['values'][field]=value;self.save()
                    with self.assertRaises(ValueError):evidence.validate(self.root)
        boundary.pop('values');self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_incomplete_or_nonboolean_root_containment_cannot_publish(self):
        check=next(x for x in self.runtime['checks'] if x['name']=='custom_service_containment')
        for field in evidence.CONTAINMENT:
            for value in (False,1,'true',None):
                with self.subTest(field=field,value=value):
                    check['values']={name:True for name in evidence.CONTAINMENT}
                    check['values'][field]=value;self.save()
                    with self.assertRaises(ValueError):evidence.validate(self.root)
        check.pop('values');self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
    def test_storage_module_and_arc_evidence_cannot_be_partial_or_forged(self):
        check=next(x for x in self.runtime['checks'] if x['name']=='storage_components')
        original=check['values'].copy()
        cases=[(key,value) for key in evidence.STORAGE_COMPONENTS for value in (False,1,'true',None)]
        cases += [('kernel','bad kernel\n'),('zfs_arc_max_bytes',True),('zfs_arc_max_bytes',0),
            ('zfs_arc_min_bytes','134217728'),('zfs_arc_size_bytes',True),('zfs_arc_size_bytes',-1),('zfs_arc_size_bytes',2**64)]
        for field,value in cases:
            with self.subTest(field=field,value=value):
                check['values']={**original,field:value};self.save()
                with self.assertRaises(ValueError):evidence.validate(self.root)
        check.pop('values');self.save()
        with self.assertRaises(ValueError):evidence.validate(self.root)
