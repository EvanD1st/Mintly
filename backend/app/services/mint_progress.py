"""Display progress from durable execution/receipt evidence, never a timer."""

KEYS = ('checking','preparing','sent','included','confirmed')
LABELS = ('Checking wallet','Preparing','Sent','Included','Confirmed')


def progress(task):
    terminal = task.status in ('failed','expired','disarmed','reverted')
    index = (4 if task.status == 'confirmed' else 3 if task.included_at or task.status == 'reverted' else
        2 if task.status == 'submitted' else 2 if task.broadcast_attempts else
        1 if task.preparation_started_at or task.signed_tx_raw else 0)
    label = LABELS[index]
    if task.status == 'armed' and not task.preparation_started_at:
        label = 'Waiting for mint time'
    elif task.status == 'uncertain' and not task.included_at:
        label = 'Checking transaction status'
    elif task.status in ('armed','preparing') and task.failure_reason:
        label = 'Waiting for mint preparation'
    elif task.included_at and task.status not in ('confirmed','reverted'):
        label = 'Included — waiting for confirmations' if task.inclusion_result == 'success' else 'Reverted — waiting for confirmations'
    if terminal:
        label = {'failed':'Preparation stopped' if not task.transaction_hash else 'Mint stopped','expired':'Mint window ended','disarmed':'Mint paused or cancelled','reverted':'Mint reverted'}[task.status]
    return {'key':KEYS[index], 'label':label, 'detail':task.failure_reason if terminal or task.status in ('armed','uncertain') else None,
        'steps':[{'key':key,'label':text,'state':('complete' if n < index or (n == index and task.status == 'confirmed') else
            'stopped' if terminal and n == index else 'current' if n == index else 'pending')}
            for n,(key,text) in enumerate(zip(KEYS,LABELS))],
        'included_at':task.included_at,'confirmed_at':task.confirmed_at}
