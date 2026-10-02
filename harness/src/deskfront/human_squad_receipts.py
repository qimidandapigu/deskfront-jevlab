"""Engine receipt reconciliation for Deskfront squad orders."""

class SquadReceiptMixin:
    def _receipts(self, receipts):
        for ident, pending in list(self.pending_commands.items()):
            receipt = receipts.get(ident)
            if receipt is None:
                continue
            pending['order']['pending'] = False
            pending['order']['accepted'] = receipt.get('accepted') is True
            self.accepted_orders += receipt.get('accepted') is True
            if pending['command']['run_id'] == self.world.get('run_id'):
                self.run_accepted_orders += receipt.get('accepted') is True
            if not receipt.get('accepted'):
                self.feedback = 'engine_rejected:' + str(receipt.get('message', 'unknown'))
                self.revision['executor'] += 1
                if pending['command']['run_id'] == self.world.get('run_id'):
                    self._wake('path_blocked', dict(reason=self.feedback))
            self._record('human-engine-receipt', command_id=ident, command=pending['command'],
                         request_id=pending['request_id'], receipt=receipt)
            del self.pending_commands[ident]

