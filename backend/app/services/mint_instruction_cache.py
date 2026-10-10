"""Signer-only encrypted verified instructions bound to an exact task intent."""
import hashlib,hmac,json,secrets,time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import settings
from app.services.custody import private_read


def cipher():
    key=hmac.new(private_read(settings.CUSTODY_PASSWORD_FILE).encode(),b'mintly/verified-instructions/v1',hashlib.sha256).digest()
    return AESGCM(key)


def tables(journal):
    journal.execute('CREATE TABLE IF NOT EXISTS mint_instruction_cache (task TEXT PRIMARY KEY,intent TEXT NOT NULL,expires_at INTEGER NOT NULL,payload BLOB NOT NULL)')


def get(journal,task_id,intent):
    try:
        tables(journal)
        row=journal.execute('SELECT * FROM mint_instruction_cache WHERE task=?',(task_id,)).fetchone()
        if not row or row['intent']!=intent or row['expires_at']<=time.time():return None
        aad=json.dumps([task_id,intent,row['expires_at']],separators=(',',':')).encode()
        data=row['payload'];result=json.loads(cipher().decrypt(data[:12],data[12:],aad))
        if set(result)!={'target','value','data'}:return None
        return result
    except Exception:return None  # Cache corruption becomes a miss, never signing authority.


def put(journal,task_id,intent,execution,expiry):
    try:
        tables(journal)
        until=min(int(expiry),int(time.time())+300)
        if until<=time.time():return
        safe={k:execution[k] for k in ('target','value','data')}
        aad=json.dumps([task_id,intent,until],separators=(',',':')).encode();nonce=secrets.token_bytes(12)
        payload=nonce+cipher().encrypt(nonce,json.dumps(safe,separators=(',',':')).encode(),aad)
        journal.execute('SAVEPOINT instruction_cache_write')
        try:
            journal.execute('DELETE FROM mint_instruction_cache WHERE expires_at<=?',(int(time.time()),))
            journal.execute('INSERT INTO mint_instruction_cache VALUES (?,?,?,?) ON CONFLICT(task) DO UPDATE SET intent=excluded.intent,expires_at=excluded.expires_at,payload=excluded.payload',
                (task_id,intent,until,payload))
            journal.execute('RELEASE instruction_cache_write')
        except Exception:
            journal.execute('ROLLBACK TO instruction_cache_write');journal.execute('RELEASE instruction_cache_write')
    except Exception:pass  # Cache persistence must not affect signing or nonce accounting.
