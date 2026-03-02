#!/usr/bin/env python3
"""Fix self.demo_checklist_state and following lines indentation"""

with open('ui_application.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the blocks that need fixing (lines starting with 8 spaces "        self." that should have 12)
in_init = False
fixed_count = 0

for i in range(len(lines)):
    # Check if we're in __init__
    if 'def __init__(self,' in lines[i]:
        in_init = True
    elif in_init and lines[i].strip().startswith('def ') and '__init__' not in lines[i]:
        in_init = False
    
    # If in __init__ and line starts with exactly 8 spaces followed by "self.", make it 12
    if in_init and lines[i].startswith('        self.') and not lines[i].startswith('            '):
        lines[i] = '    ' + lines[i]  # Add 4 more spaces
        fixed_count += 1
    # Also fix comments
    elif in_init and lines[i].startswith('        #') and not lines[i].startswith('            '):
        lines[i] = '    ' + lines[i]  # Add 4 more spaces
        fixed_count += 1

with open('ui_application.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"✓ Fixed {fixed_count} lines in __init__")
