"""Patch only the retrieval functions in backend/app/phase3.py. Run from project root."""
from pathlib import Path
import ast
import shutil
import sys

source = Path('backend/app/phase3.py')
helper = Path(__file__).with_name('retrieval_upgrade.py')
if not source.exists():
    sys.exit('Run from quantbook-ai root: backend/app/phase3.py not found')
text = source.read_text()
tree = ast.parse(text)
functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
if 'retrieve_chunks' not in functions or 'cosine' not in functions:
    sys.exit('Expected retrieve_chunks() and cosine() missing. No changes made.')
if 'Phase 3.1.1 retrieval helpers' in text:
    sys.exit('Upgrade already installed. No changes made.')
helper_text = helper.read_text()
helper_tree = ast.parse(helper_text)
start = next(n for n in helper_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'retrieval_clean')
replacement = '\n\n' + '\n'.join(helper_text.splitlines()[start.lineno - 1:]) + '\n'
# Preserve the user's current generator, validation, and API code.
node = functions['retrieve_chunks']
lines = text.splitlines(keepends=True)
lines[node.lineno-1:node.end_lineno] = [replacement]
new_text = ''.join(lines)
# Add helper imports and constants at module level, not inside another function.
header = "\n# Phase 3.1.1 retrieval helpers (no model calls)\n" + '\n'.join(
    helper_text.splitlines()[helper_tree.body[3].lineno - 1:helper_tree.body[3].end_lineno]
) if False else ''
# Constants are extracted from helper source before first function.
constants = helper_text.split('def retrieval_clean(', 1)[0]
constants = constants.replace('"""QuantBook AI Phase 3.1.1 retrieval helpers. No model calls or schema changes."""', '')
new_text += '\n\n# Phase 3.1.1 helper constants\n' + constants + '\n'
compile(new_text, str(source), 'exec')
backup = source.with_name('phase3.py.phase3_1_pre_retrieval')
if backup.exists():
    sys.exit(f'Backup already exists: {backup}. No changes made.')
shutil.copy2(source, backup)
source.write_text(new_text)
print(f'Installed Phase 3.1.1 retrieval ranking. Backup: {backup}')
