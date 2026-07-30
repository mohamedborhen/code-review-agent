import sys, os, glob
sys.path.insert(0, 'backend/src/code_review_agent')

from sqlmodel import Session, select
from infrastructure.db.engine import engine
from infrastructure.db.models import RepoWorkspace, GraphSnapshot

with Session(engine) as s:
    ws = s.exec(select(RepoWorkspace).where(RepoWorkspace.repo_id == 'mohamedborhen/CLIP-DRDG')).first()
    if ws:
        commit = ws.last_synced_commit[:12] if ws.last_synced_commit else 'None'
        print(f'Workspace: {ws.repo_id} -> Commit: {commit}')
        g = list(glob.glob(os.path.join(ws.local_path, '.code-review-graph', '*.db')))
        print(f'Graph DB file exists on disk: {"yes" if g else "no"}')
    else:
        print('Workspace: Not found in DB')

    snap = s.exec(select(GraphSnapshot).where(GraphSnapshot.repo_id == 'mohamedborhen/CLIP-DRDG').order_by(GraphSnapshot.id.desc())).first()
    if snap:
        print(f'Snapshot: {snap.commit_hash[:12]} status={snap.status}')
    else:
        print('Snapshot: Not found in DB')
