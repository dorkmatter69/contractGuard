"""Rail-neutral monetary authorization, separate from resource credits and billing.

This ledger authorizes commitments. It never asserts an external payment occurred.
Reservations remain held pending a future audited chain/provider reconciliation.
"""
import json
import re
from dataclasses import asdict, dataclass
from .core import Denied, canonical, digest

RAILS = frozenset({'evm-escrow', 'x402', 'stripe-connect'})


@dataclass(frozen=True)
class MoneyBudget:
    mandate: str
    rail: str
    asset: str  # e.g. eip155:84532/erc20:0x...; no implicit conversion or FX.
    limit: int  # Exact asset base units, NOT a float and NOT resource credits.
    payees: tuple[str, ...]


class EconomicLedger:
    def __init__(self, guard):
        self.guard = guard
        with guard.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS money_budgets(mandate TEXT NOT NULL,rail TEXT NOT NULL,
                asset TEXT NOT NULL,body TEXT NOT NULL,committed BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY(mandate,rail,asset));
            CREATE TABLE IF NOT EXISTS commitments(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,
                body TEXT NOT NULL,state TEXT NOT NULL);
            ''')

    def allocate(self, budget: MoneyBudget):
        if (budget.rail not in RAILS or not isinstance(budget.asset, str) or not budget.asset
                or type(budget.limit) is not int or not 0 <= budget.limit <= 2**63 - 1
                or not isinstance(budget.payees, (tuple, list)) or not budget.payees
                or any(not isinstance(p, str) or not p for p in budget.payees)):
            raise ValueError('invalid monetary budget')
        with self.guard.tx() as db:
            lineage = self.guard.chain(db, budget.mandate)
            if len(lineage) > 1:
                parent = self.budget(db, lineage[1][0]['id'], budget.rail, budget.asset)
                terms = json.loads(parent['body'])
                if budget.limit > terms['limit'] or not set(budget.payees) <= set(terms['payees']):
                    raise Denied('monetary delegation expands authority')
            db.execute('INSERT INTO money_budgets(mandate,rail,asset,body) VALUES(?,?,?,?)',
                       (budget.mandate, budget.rail, budget.asset, canonical(asdict(budget))))
            self.guard.event(db, 'money.allocated', budget=asdict(budget))

    @staticmethod
    def budget(db, mandate, rail, asset):
        row = db.execute('SELECT * FROM money_budgets WHERE mandate=? AND rail=? AND asset=?',
                         (mandate, rail, asset)).fetchone()
        if row is None:
            raise Denied('monetary authority missing')
        return row

    def reserve(self, id, mandate, agent, assignment, ticket, rail, asset, amount, payee, expires):
        if (not isinstance(id, str) or not id or type(amount) is not int
                or not 0 < amount <= 2**63 - 1 or type(expires) is not int):
            raise ValueError('invalid commitment')
        body = dict(id=id, mandate=mandate, agent=agent, assignment=assignment, ticket=ticket,
                    rail=rail, asset=asset, amount=amount, payee=payee, expires=expires)
        fingerprint = digest(body)
        with self.guard.tx() as db:
            lineage = self.guard.chain(db, mandate)
            self.guard.check_assignment(db, assignment, agent, mandate)
            a = db.execute('SELECT ticket,expires FROM assignments WHERE id=?', (assignment,)).fetchone()
            if (a['ticket'] != ticket or lineage[0][0]['agent'] != agent
                    or not self.guard.clock() < expires <= min(a['expires'], lineage[0][0]['expires'])):
                raise Denied('commitment exceeds ticket or lease')
            existing = db.execute('SELECT fingerprint FROM commitments WHERE id=?', (id,)).fetchone()
            if existing:
                if existing['fingerprint'] != fingerprint:
                    raise Denied('commitment key conflict')
                return body
            accounts = [self.budget(db, m['id'], rail, asset) for m, _ in lineage]
            for account in accounts:
                terms = json.loads(account['body'])
                if payee not in terms['payees'] or account['committed'] + amount > terms['limit']:
                    raise Denied('monetary budget or payee denied')
            for account in accounts:
                db.execute('UPDATE money_budgets SET committed=committed+? WHERE mandate=? AND rail=? AND asset=?',
                           (amount, account['mandate'], rail, asset))
            db.execute('INSERT INTO commitments VALUES(?,?,?,?)', (id, fingerprint, canonical(body), 'RESERVED'))
            self.guard.event(db, 'money.reserved', commitment=body)
        return body

    def acceptance(self, id, binding):
        """Prepare typed data only after deterministic acceptance; never sign/broadcast.

        Binding is supplied by a TRUSTED observer after matching funded on-chain
        terms. No RPC observer is shipped yet, so the caller must independently
        verify token, amount, payee, validator, expiry and mandate before this call.
        """
        with self.guard.tx() as db:
            row = db.execute('SELECT body FROM commitments WHERE id=?', (id,)).fetchone()
            if row is None:
                raise Denied('unknown economic commitment')
            commitment = json.loads(row['body'])
            if commitment['rail'] != 'evm-escrow':
                raise Denied('rail does not use EVM escrow attestations')
            self.guard.chain(db, commitment['mandate'])
            ticket = db.execute('SELECT * FROM tickets WHERE id=?', (commitment['ticket'],)).fetchone()
            if ticket is None or ticket['state'] != 'ACCEPTED':
                raise Denied('accepted artifact required')
            mandate = db.execute('SELECT body FROM mandates WHERE id=?', (commitment['mandate'],)).fetchone()
            if (binding.expires != commitment['expires'] or binding.deadline > commitment['expires']
                    or binding.deadline < self.guard.clock() or self.guard.clock() >= binding.expires
                    or binding.asset != commitment['asset'] or binding.amount != commitment['amount']
                    or binding.payee.lower() != commitment['payee'].lower()
                    or binding.mandate_hash != '0x' + digest(json.loads(mandate['body']))
                    or binding.validator_hash != '0x' + digest(ticket['validator'])):
                raise Denied('funded terms mismatch')
            artifact_hash = '0x' + digest(json.loads(ticket['artifact']))
            result = binding.typed_data(artifact_hash)
            self.guard.event(db, 'money.acceptance_prepared', commitment=id, typed_data_hash=digest(result))
            return result


@dataclass(frozen=True)
class EscrowBinding:
    chain_id: int
    escrow: str
    task_id: str
    asset: str
    payee: str
    amount: int
    expires: int
    mandate_hash: str
    validator_hash: str
    deadline: int
    validator: str
    settlement_nonce: int

    def typed_data(self, artifact_hash):
        if any(type(v) is not int or v <= 0 for v in (self.amount, self.expires, self.deadline)):
            raise ValueError('positive integer amount and deadlines required')
        if type(self.chain_id) is not int or self.chain_id not in (84532, 31337):
            raise ValueError('testnet/local chain required')
        if type(self.settlement_nonce) is not int or self.settlement_nonce < 0:
            raise ValueError('nonnegative settlement nonce required')
        for address in (self.escrow, self.payee, self.validator):
            if not re.fullmatch(r'0x[0-9a-fA-F]{40}', address) or int(address[2:], 16) == 0:
                raise ValueError('invalid address')
        if not self.asset.startswith(f'eip155:{self.chain_id}/erc20:'):
            raise ValueError('asset chain mismatch')
        token = self.asset.split('/erc20:')[1]
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}', token) or int(token[2:], 16) == 0:
            raise ValueError('invalid token')
        for value in (self.task_id, self.mandate_hash, self.validator_hash, artifact_hash):
            if not re.fullmatch(r'0x[0-9a-fA-F]{64}', value) or int(value[2:], 16) == 0:
                raise ValueError('invalid commitment hash')
        fields = lambda pairs: [{'name': name, 'type': type} for name, type in pairs]
        return {
            'types': {
                'EIP712Domain': fields([('name','string'), ('version','string'), ('chainId','uint256'),
                                       ('verifyingContract','address')]),
                'Acceptance': fields([('taskId','bytes32'), ('mandateHash','bytes32'), ('artifactHash','bytes32'),
                                      ('validatorHash','bytes32'), ('validator','address'), ('settlementNonce','uint256'), ('deadline','uint256')])},
            'primaryType': 'Acceptance',
            'domain': {'name': 'ContractGuardTaskEscrow', 'version': '2',
                       'chainId': self.chain_id, 'verifyingContract': self.escrow},
            'message': {'taskId': self.task_id, 'mandateHash': self.mandate_hash,
                        'artifactHash': artifact_hash, 'validatorHash': self.validator_hash,
                        'validator': self.validator, 'settlementNonce': self.settlement_nonce, 'deadline': self.deadline}}
