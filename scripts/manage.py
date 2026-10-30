"""Local administrative commands. Run with the backend Python environment."""
import argparse
import getpass
from pathlib import Path
import sys
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'backend')]
load_dotenv(root/'.env')
from lifecycle import initialize
from database import SessionLocal
from portal_models import Account, SCHEMA_VERSION
from security import password_hash


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['migrate','create-operator','reset-password'])
    args=parser.parse_args()
    initialize()
    if args.command=='migrate':
            print(f'Portal schema v{SCHEMA_VERSION} is ready. Catalogue filters and candidate review reasons are in place.');return
    email=input('Account email: ').strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:raise SystemExit('Invalid email.')
    password=getpass.getpass('Password (12–128 characters, hidden): ')
    if not 12<=len(password)<=128:raise SystemExit('Password length is invalid.')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords did not match.')
    with SessionLocal() as db:
        account=db.query(Account).filter_by(email=email).first()
        if args.command=='create-operator':
            if account:raise SystemExit('Account already exists; no role was changed.')
            account=Account(email=email,name=input('Display name: ').strip() or 'Operator',role='operator',password_hash=password_hash(password));db.add(account)
        else:
            if not account:raise SystemExit('Account does not exist.')
            from portal_models import LoginSession
            account.password_hash=password_hash(password)
            db.query(LoginSession).filter_by(account_id=account.id).delete()
        db.commit()
    print('Account updated. Password was not printed.')


if __name__=='__main__':main()
