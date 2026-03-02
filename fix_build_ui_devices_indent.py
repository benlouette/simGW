#!/usr/bin/env python3
"""Fix _build_ui_devices indentation - all should be 12 spaces"""

with open('ui_application.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find _build_ui_devices and fix all lines inside
for i, line in enumerate(lines):
    if '    def _build_ui_devices(self, parent: tk.Frame) -> None:' in line:
        # Find end (next def at same level)
        end_i = i + 1
        for j in range(i + 1, len(lines)):
            if '    def _build_ui_settings(self, parent: tk.Frame) -> None:' in lines[j]:
                end_i = j
                break
        
        # Fix all lines that have 8 spaces (should be 12)
        fixed = 0
        for k in range(i + 1, end_i):
            if lines[k].startswith('        ') and not lines[k].startswith('            '):
                # Has 8 spaces, need to add 4
                lines[k] = '    ' + lines[k]
                fixed += 1
        
        print(f"✓ Fixed {fixed} lines in _build_ui_devices (lines {i+1}-{end_i})")
        break

with open('ui_application.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("✅ _build_ui_devices indentation fixed!")
