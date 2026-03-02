#!/usr/bin/env python3
"""Fix _devices_scan indentation completely"""

with open('ui_application.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find _devices_scan function and replace it completely
for i, line in enumerate(lines):
    if '    def _devices_scan(self) -> None:' in line:
        # Find the end (_devices_populate starts next)
        end_i = i
        for j in range(i + 1, len(lines)):
            if '    def _devices_populate(self, pairs):' in lines[j]:
                end_i = j
                break
        
        # Build correct function
        new_func = [
            '    def _devices_scan(self) -> None:\n',
            '        """Trigger one scan pass and merge results into the Devices table (no clear, no dup)."""\n',
            '        # Prevent concurrent scans (fix thread leak)\n',
            '        if self._devices_scan_in_progress:\n',
            '            return\n',
            '        \n',
            '        self._devices_scan_in_progress = True\n',
            '        \n',
            '        try:\n',
            '            self.devices_scan_status_var.set("\\U0001F50D Scanning...")\n',
            '            self.root.update_idletasks()\n',
            '        except Exception:\n',
            '            pass\n',
            '\n',
            '        # Read current filters (use fixed 5s timeout)\n',
            '        addr_prefix, _mtu, _scan_timeout, _rx_timeout, _rec, _sess, name_contains, svc_contains, mfg_id_hex, mfg_data_hex = self._read_runtime_params()\n',
            '        timeout_s = 5.0  # Fixed 5 second timeout\n',
            '\n',
            '        def worker():\n',
            '            try:\n',
            '                async def _do():\n',
            '                    from bleak import BleakScanner\n',
            '                    # return_adv=True gives (device, adv) pairs on most backends\n',
            '                    res = await BleakScanner.discover(timeout=timeout_s, return_adv=True)\n',
            '                    pairs = []\n',
            '                    if isinstance(res, dict):\n',
            '                        for _addr, val in res.items():\n',
            '                            if isinstance(val, tuple) and len(val) == 2:\n',
            '                                pairs.append(val)\n',
            '                            else:\n',
            '                                pairs.append((val, None))\n',
            '                    elif isinstance(res, list):\n',
            '                        for item in res:\n',
            '                            if isinstance(item, tuple) and len(item) == 2:\n',
            '                                pairs.append(item)\n',
            '                            else:\n',
            '                                pairs.append((item, None))\n',
            '                    return pairs\n',
            '\n',
            '                pairs = asyncio.run(_do())\n',
            '                self.root.after(0, lambda: self._devices_populate(pairs))\n',
            '            except Exception as exc:\n',
            '                # Do not crash autoscan; just report\n',
            '                self.root.after(0, lambda: self.devices_scan_status_var.set(f"\\u274c Error: {type(exc).__name__}"))\n',
            '            finally:\n',
            '                # Always reset flag when scan completes\n',
            '                self.root.after(0, lambda: setattr(self, \'_devices_scan_in_progress\', False))\n',
            '\n',
            '        threading.Thread(target=worker, daemon=True).start()\n',
            '\n',
        ]
        
        # Replace
        lines[i:end_i] = new_func
        print(f"✓ Fixed _devices_scan from line {i+1} to {end_i+1}")
        break

with open('ui_application.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("✅ Indentation fixed!")
