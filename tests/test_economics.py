from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from contractguard import Denied, Mandate
from contractguard.core import digest
from contractguard.economics import EconomicLedger, EscrowBinding, MoneyBudget
from tests_support import Fixture


class EconomicTests(Fixture):
    def setUp(self):
        super().setUp()
        self.ledger = EconomicLedger(self.guard)
        self.payee = '0x' + '12' * 20
        self.asset = 'eip155:84532/erc20:0x' + '34' * 20
        self.guard.create_ticket('t', 'root', 'v1')
        self.guard.assign('a', 't', 'parent', 190)
        self.budget = MoneyBudget('root', 'evm-escrow', self.asset, 100, (self.payee,))
        self.ledger.allocate(self.budget)

    def reserve(self, id='order', **kwargs):
        terms = dict(id=id, mandate='root', agent='parent', assignment='a', ticket='t', rail='evm-escrow',
                     asset=self.asset, amount=60, payee=self.payee, expires=180)
        terms.update(kwargs)
        return self.ledger.reserve(**terms)

    def binding(self):
        return EscrowBinding(84532, '0x' + '56' * 20, '0x' + '78' * 32, self.asset, self.payee, 60, 180,
                             '0x' + digest(self.root.__dict__), '0x' + digest('v1'), 170, '0x' + '9a' * 20, 0)

    def test_separate_money_and_resource_budgets(self):
        self.reserve()
        with self.guard.tx() as db:
            self.assertEqual(db.execute("SELECT spent FROM mandates WHERE id='root'").fetchone()['spent'], 0)
        with self.assertRaises(Denied): self.reserve('other')

    def test_idempotency_and_binding(self):
        self.assertEqual(self.reserve(), self.reserve())
        with self.assertRaises(Denied): self.reserve(amount=59)

    def test_payee_and_asset_authority(self):
        for kwargs in ({'payee': 'foreign'}, {'asset': 'USD'}, {'agent': 'other'}, {'ticket': 'other'}):
            with self.assertRaises(Denied): self.reserve(**kwargs)

    def test_concurrent_reservations_cannot_overspend(self):
        def invoke(i):
            try:
                self.reserve(str(i), amount=30)
                return 1
            except Denied:
                return 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(invoke, range(12))), 3)

    def test_attenuated_child_money_budgets(self):
        child = Mandate('child', 'tenant', 'worker', ('run',), 6, 190, parent='root', depth=1)
        self.guard.issue(child)
        with self.assertRaises(Denied): self.ledger.allocate(replace(self.budget, mandate='child', limit=101))
        with self.assertRaises(Denied): self.ledger.allocate(replace(self.budget, mandate='child', payees=('foreign',)))
        self.ledger.allocate(replace(self.budget, mandate='child', limit=90))
        self.guard.create_ticket('ct', 'child', 'v1'); self.guard.assign('ca', 'ct', 'worker', 190)
        self.reserve('child-order', mandate='child', agent='worker', assignment='ca', ticket='ct', amount=90)
        with self.assertRaises(Denied): self.reserve()

    def test_acceptance_requires_validated_exact_artifact(self):
        self.reserve()
        with self.assertRaises(Denied): self.ledger.acceptance('order', self.binding())
        artifact = {'valid': True}
        self.guard.submit('a', 'parent', artifact, {'v1': lambda a: True})
        data = self.ledger.acceptance('order', self.binding())
        self.assertEqual(data['message']['artifactHash'], '0x' + digest(artifact))
        self.assertEqual(data['domain']['chainId'], 84532)
        for change in ({'amount': 61}, {'asset': 'wrong'}, {'mandate_hash': '0x' + '11'*32},
                       {'deadline': 181}, {'validator_hash': '0x' + '22'*32}):
            with self.assertRaises(Denied): self.ledger.acceptance('order', replace(self.binding(), **change))

    def test_explicit_validator_nonce_and_domain_version(self):
        data = self.binding().typed_data('0x' + '11' * 32)
        self.assertEqual(data['domain']['version'], '2')
        self.assertEqual(data['message']['validator'], self.binding().validator)
        self.assertEqual(data['message']['settlementNonce'], 0)
        with self.assertRaises(ValueError):
            replace(self.binding(), settlement_nonce=-1).typed_data('0x' + '11' * 32)

    def test_revoked_mandate_cannot_prepare_acceptance(self):
        self.reserve()
        self.guard.submit('a', 'parent', {}, {'v1': lambda a: True})
        self.guard.revoke('root')
        with self.assertRaises(Denied): self.ledger.acceptance('order', self.binding())

    def test_expired_mandate_cannot_prepare_acceptance(self):
        self.reserve()
        self.guard.submit('a', 'parent', {}, {'v1': lambda a: True})
        self.now = 200
        with self.assertRaisesRegex(Denied, 'expired'):
            self.ledger.acceptance('order', self.binding())

    def test_mainnet_typed_data_refused(self):
        with self.assertRaises(ValueError): replace(self.binding(), chain_id=8453).typed_data('0x'+'11'*32)

    def test_expired_commitment_refused(self):
        with self.assertRaises(Denied): self.reserve(expires=201)

    def test_api_money_budget_is_operator_only(self):
        import hashlib
        import io
        import json
        from contractguard.service import Application, Identity
        app = Application(self.guard, 'tenant', {hashlib.sha256(b'worker').hexdigest(): Identity('agent','parent')}, {})
        data = json.dumps(dict(mandate='root',rail='x402',asset=self.asset,limit=100,payees=[self.payee])).encode()
        environ = dict(HTTP_AUTHORIZATION='Bearer worker', REQUEST_METHOD='POST', CONTENT_TYPE='application/json',
                       CONTENT_LENGTH=str(len(data)), PATH_INFO='/v1/economic/budgets')
        environ['wsgi.input'] = io.BytesIO(data)
        statuses = []
        list(app(environ, lambda status, headers: statuses.append(status)))
        self.assertEqual(statuses, ['403 Forbidden'])

    def test_future_x402_backend_fails_closed(self):
        from contractguard.rails import UnavailableRail
        with self.assertRaises(NotImplementedError): UnavailableRail().purchase('order', b'quote')
